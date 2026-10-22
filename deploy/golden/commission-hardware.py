#!/usr/bin/env python3
"""Installer helper: diagnose and apply the selected fresh-post hardware map."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/opt/sammoy/sammoy2')
DISPLAY_SOURCE = None  # Standalone delivery embeds the reviewed helper here.


def get(path):
    req = urllib.request.Request('http://127.0.0.1:8090' + path,
                                 headers={'X-Commissioning-Client-IP': '127.0.0.1'})
    return json.load(urllib.request.urlopen(req, timeout=5))


def elevate(post):
    if os.geteuid() == 0:
        return
    # This belongs to the logged-in installer; never print or transmit it.
    lines = (Path.home() / 'labrix-first-login.txt').read_text().splitlines()
    passwords = [s.split(': ', 1)[1] for s in lines if s.startswith('Linux admin / sudo password: ')]
    if len(passwords) != 1:
        raise RuntimeError('Initial sudo credential unavailable; use sudo manually')
    result = subprocess.run(['sudo', '-S', '-p', '', '--', sys.executable,
                             str(Path(__file__).resolve()), '--post', str(post)],
                            input=passwords[0] + '\n', text=True)
    raise SystemExit(result.returncode)


def command(*args, timeout=15):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def redact(text):
    env = ROOT / '.env'
    if env.is_file():
        for line in env.read_text().splitlines():
            if '=' not in line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            value = value.strip().strip('\"\'')
            if value and any(s in key for s in ('PASSWORD', 'SECRET', 'TOKEN', 'API_KEY', 'SETUP_KEY', 'DSN')):
                text = text.replace(value, '[redacted]')
    return text


def diagnosis():
    profile = (ROOT / '.hardware-profile').read_text().strip()
    result = {'hardware_profile': profile,
              'required_nodes': {p: Path(p).is_char_device() for p in ('/dev/ttyUSB0', '/dev/gpiochip0', '/dev/i2c-7')},
              'usb_serial_nodes': sorted(str(p) for pattern in ('ttyUSB*', 'ttyACM*') for p in Path('/dev').glob(pattern))}
    containers = command('docker', 'ps', '-a', '--format', '{{.Names}}: {{.Status}}')
    result['containers'] = containers.stdout.strip().splitlines()
    health = command('docker', 'exec', 'sammoy2-io-helper', 'python', '-c',
                     'import json,urllib.request;d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/io",timeout=3));print(json.dumps({k:d.get(k) for k in ("modbus_ok","outputs","last_poll_at","poll_age_seconds")}))')
    if health.returncode == 0:
        result['io'] = json.loads(health.stdout)
    else:
        result['io'] = {'reachable': False, 'message': redact(health.stderr.strip())[:600]}
    return result


def restore_orientation():
    source = DISPLAY_SOURCE
    if source is None:
        source = (Path(__file__).resolve().parent.parent / 'minimal-kiosk/restore-display.py').read_text()
    target = ROOT / 'deploy/minimal-kiosk/restore-display.py'
    target.write_text(source); target.chmod(0o644)
    dropin = Path('/etc/systemd/system/hdmi-toggle-once.service.d')
    dropin.mkdir(parents=True, exist_ok=True)
    (dropin / '90-labrix-orientation.conf').write_text(
        '[Service]\nExecStartPost=/usr/bin/python3 /opt/sammoy/sammoy2/deploy/minimal-kiosk/restore-display.py\n')
    command('systemctl', 'daemon-reload')
    applied = command('/usr/bin/python3', str(target), timeout=25)
    print(redact(applied.stdout or applied.stderr).strip(), flush=True)


def main(post):
    status = get('/api/commissioning/status')
    state = get('/api/wash/state')['state']
    if status.get('site', {}).get('post_no') != post or post in (1, 2):
        raise RuntimeError('Wrong station; refuses to change primary/standby posts')
    if status.get('commissioning', {}).get('complete'):
        raise RuntimeError('This helper is limited to unfinished commissioning')
    if any(state.get(k) for k in ('creditSum', 'activeSessionId', 'activeMode', 'armedMode', 'requestedOutput', 'walletTransferPending', 'walletCashHeld')):
        raise RuntimeError('Post is not idle; no changes made')
    before = diagnosis()
    print('BEFORE ' + json.dumps(before, ensure_ascii=False), flush=True)
    restore_orientation()
    if before['hardware_profile'] == 'factory-only':
        if not all(before['required_nodes'].values()):
            print('Hardware profile not applied: required device nodes are missing.', flush=True)
            return
        print('Applying the selected hardware profile. Startup keeps all outputs OFF.', flush=True)
        result = None
        try:
            result = command('/bin/sh', 'deploy/apply-device-profile.sh', timeout=420)
            print(redact(result.stdout + result.stderr)[-6000:], flush=True)
        finally:
            if result is None or result.returncode:
                # Restore installer access also on timeout/interruption.
                command('docker', 'start', 'sammoy2-wash-engine', timeout=30)
                print('Hardware application failed; installation backend restarted. No data reset.', flush=True)
    after = diagnosis()
    print('AFTER ' + json.dumps(after, ensure_ascii=False), flush=True)
    for _ in range(20):
        try:
            status = get('/api/commissioning/status')
            print('RESULT ' + json.dumps({'post': status['site']['post_no'], 'io_ready': status['io_ready'],
                                          'commissioned': status['commissioning']['complete']}), flush=True)
            break
        except Exception:
            time.sleep(1)
    else:
        print('Backend still starting; refresh the installer shortly.', flush=True)
    if after.get('io', {}).get('modbus_ok') is not True:
        logs = command('docker', 'logs', '--tail', '100', 'sammoy2-io-helper')
        allowed = []
        for line in (logs.stdout + logs.stderr).splitlines():
            lower = line.lower()
            if any(k in lower for k in ('modbus', 'serial', 'ttyusb', 'connection', 'no response')) and not any(k in lower for k in ('rfid', 'uid', 'password', 'token', 'secret')):
                allowed.append(redact(line))
        print('MODBUS_DIAGNOSTICS\n' + '\n'.join(allowed[-20:]), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--post', required=True, type=int)
    args = parser.parse_args()
    elevate(args.post)
    try:
        main(args.post)
    except Exception as exc:
        print('STOPPED: ' + redact(str(exc)), flush=True)
        raise SystemExit(1)
