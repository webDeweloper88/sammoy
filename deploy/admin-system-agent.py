#!/usr/bin/python3
"""Local root-only maintenance bridge. Fixed actions; no shell or public port."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import threading
import time
from uuid import UUID
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer

ROOT = Path('/opt/sammoy/sammoy2')
SOCKET = Path('/run/sammoy2-admin/system.sock')
STATE = Path('/var/lib/sammoy2-admin/system-job.json')
ACTIONS = frozenset(('reboot', 'poweroff', 'settings', 'full', 'hardware'))
lock = threading.Lock()
busy = False


def validate(value):
    if not isinstance(value, dict) or set(value) != {'action', 'request_id', 'actor'}:
        raise ValueError('Invalid action request')
    if value['action'] not in ACTIONS:
        raise ValueError('Unknown action')
    return {'action': value['action'], 'request_id': str(UUID(value['request_id'])),
            'actor': str(value['actor'])[:80]}


def save(job):
    job = {**job, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = STATE.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as target:
        json.dump(job, target)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, STATE)


def run(args):
    # Do not persist subprocess output: it may contain credentials from tools.
    subprocess.run(args, cwd=ROOT, check=True, timeout=480,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def compose(profile):
    files = {'full': [], 'factory-only': ['docker-compose.factory.yml'],
             'relay-only': ['docker-compose.relay-only.yml'],
             'nfc-relay': ['docker-compose.nfc-relay.yml'],
             'dry-fog': ['docker-compose.nfc-relay.yml', 'docker-compose.dry-fog.yml']}
    if profile not in files:
        raise ValueError('Invalid hardware profile')
    return ['docker', 'compose', '-f', 'docker-compose.yml'] + [x for f in files[profile] for x in ('-f', f)]


def perform(action):
    if action == 'hardware':
        run(['/usr/bin/timeout', '--signal=TERM', '--kill-after=15', '420',
             '/usr/bin/python3', str(ROOT / 'deploy/apply-commissioning-profile.py')])
        return
    profile = (ROOT / '.hardware-profile').read_text().strip() if (ROOT / '.hardware-profile').exists() else 'full'
    command = compose(profile)
    # Engine flushes financial state and requests OFF before helper exits.
    run(command + ['stop', '-t', '30', 'wash-engine', 'telegram-reports'])
    run(command + ['stop', '-t', '15', 'io-helper'])
    if action in ('reboot', 'poweroff'):
        run(['systemctl', action])
        return
    extra = []
    journal = ROOT / 'data/io-helper/nv9.sqlite3'
    if journal.exists():
        # Read-only: helper is stopped. Never zero/recreate its stream.
        with sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True) as connection:
            stream, total = connection.execute('SELECT stream,total FROM counter WHERE id=1').fetchone()
        extra = ['-e', 'RESET_NV9_STREAM=' + stream, '-e', 'RESET_NV9_TOTAL=' + str(total)]
    run(command + ['run', '--rm', '--no-deps'] + extra + ['wash-engine', 'python', '-m', 'app.system_reset', action])
    if action == 'full':
        # A fog engine must not boot without its erased wallet inventory.
        if profile != 'factory-only':
            (ROOT / '.hardware-profile.before-factory-reset').write_text(profile + '\n')
        (ROOT / '.hardware-profile').write_text('factory-only\n')
        # Fixed container paths only, no host directory recursion or shell.
        clear = "from pathlib import Path; import shutil; p=Path('/data'); [(x.unlink() if x.is_symlink() or not x.is_dir() else shutil.rmtree(x)) for x in p.iterdir()]"
        run(command + ['run', '--rm', '--no-deps', '--entrypoint', 'python', 'telegram-reports', '-c', clear])
        clear_assets = clear.replace("Path('/data')", "Path('/var/lib/rtu-wash/kiosk-assets')")
        run(command + ['run', '--rm', '--no-deps', 'wash-engine', 'python', '-c', clear_assets])
    run([str(ROOT / 'deploy/start-post.sh')])
    if action == 'full':
        # Cleanup failure must not turn an already completed reset into failure.
        try:
            run(['/usr/bin/python3', str(ROOT / 'deploy/storage-maintenance.py'), '--reset'])
        except (subprocess.SubprocessError, OSError):
            print('Optional storage cleanup deferred after reset', flush=True)


def worker(job):
    global busy
    time.sleep(3)  # Let the browser receive its accepted response.
    try:
        save({**job, 'status': 'running'})
        perform(job['action'])
        save({**job, 'status': 'completed'})
    except Exception:
        # Leave stopped on failure. No partial reset is automatically retried.
        save({**job, 'status': 'failed', 'message': 'Maintenance stopped; installer review required'})
    finally:
        with lock:
            busy = False


def job_status(request_id):
    request_id=str(UUID(request_id))
    previous=json.loads(STATE.read_text()) if STATE.exists() else {}
    if previous.get('request_id')!=request_id:
        return 404,{'detail':'Maintenance operation not found'}
    return 200,{'ok':True,**{key:previous.get(key) for key in ('request_id','action','status')}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        status,result=404,{'detail':'Not found'}
        try:
            _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=0 or not self.path.startswith('/actions/'):raise ValueError('Forbidden')
            with lock:status,result=job_status(self.path.removeprefix('/actions/'))
        except (ValueError,TypeError,OSError):pass
        encoded=json.dumps(result).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)

    def do_POST(self):
        global busy
        status, result = 400, {'detail': 'Invalid request'}
        try:
            _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != 0 or self.path != '/actions':
                raise ValueError('Forbidden')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError('Invalid body')
            job = validate(json.loads(self.rfile.read(length)))
            with lock:
                previous = json.loads(STATE.read_text()) if STATE.exists() else {}
                if previous.get('request_id') == job['request_id']:
                    status, result = 202, previous
                elif busy or previous.get('status') in ('accepted', 'running') or (previous.get('status') == 'failed' and previous.get('action') != 'hardware'):
                    status, result = 409, {'detail': 'Review the existing maintenance job'}
                else:
                    result = {**job, 'status': 'accepted', 'ok': True}
                    save(result)
                    busy = True
                    threading.Thread(target=worker, args=(job,), daemon=True).start()
                    status = 202
        except (ValueError, TypeError, KeyError, OSError):
            pass
        encoded = json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == '__main__':
    os.umask(0o077)
    SOCKET.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if STATE.exists():
        previous = json.loads(STATE.read_text())
        if (previous.get('action') in ('reboot', 'poweroff') and previous.get('status') == 'running'
                and previous.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
            save({**previous, 'status': 'completed'})
    if STATE.exists():
        previous = json.loads(STATE.read_text())
        if previous.get('action') == 'hardware' and previous.get('status') in ('accepted', 'running'):
            save({**previous, 'status': 'failed'})
    SOCKET.unlink(missing_ok=True)
    with UnixStreamServer(str(SOCKET), Handler) as server:
        os.chmod(SOCKET, 0o600)
        server.serve_forever()
