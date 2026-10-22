#!/usr/bin/python3
"""Reapply configured orientation after the vendor HDMI mode toggle."""
import os
from pathlib import Path
import re
import subprocess
import time


def restore():
    values = {}
    for line in Path('/etc/sammoy2/display.conf').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    output = values.get('KIOSK_OUTPUT', '')
    rotation = values.get('KIOSK_ROTATION', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', output) or rotation not in ('normal', 'right', 'left', 'inverted'):
        raise RuntimeError('Invalid display configuration')
    for _ in range(30):
        cookies = [Path('/home/kiosk/.Xauthority')]
        if Path('/run/sddm').is_dir():
            cookies += sorted(Path('/run/sddm').iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for cookie in cookies:
            if not cookie.is_file():
                continue
            env = {**os.environ, 'DISPLAY': ':0', 'XAUTHORITY': str(cookie)}
            result = subprocess.run(['xrandr', '--query'], env=env, capture_output=True, text=True)
            if result.returncode or not any(line.startswith(output + ' connected') for line in result.stdout.splitlines()):
                continue
            subprocess.run(['xrandr', '--output', output, '--rotate', rotation], env=env, check=True)
            for args in (('s', 'off'), ('-dpms',), ('s', 'noblank')):
                subprocess.run(['xset', *args], env=env, capture_output=True)
            print('LABRIX display restored: ' + output + ' / ' + rotation)
            return
        time.sleep(.5)
    raise RuntimeError('X display unavailable for orientation restore')


if __name__ == '__main__':
    restore()
