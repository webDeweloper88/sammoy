#!/usr/bin/python3
"""Fixed host action for an idle, unfinished installer. No caller paths/commands."""
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path('/opt/sammoy/sammoy2')


def get(path):
    request = urllib.request.Request('http://127.0.0.1:8090/api/' + path,
                                     headers={'X-Commissioning-Client-IP': '127.0.0.1'})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def apply():
    if get('commissioning/status')['commissioning']['complete']:
        raise RuntimeError('Commissioning is already closed')
    state = get('wash/state')['state']
    if any(state.get(k) for k in ('creditSum', 'activeSessionId', 'activeMode',
                                  'armedMode', 'requestedOutput', 'walletTransferPending',
                                  'walletCashHeld', 'vipRemainingSeconds')):
        raise RuntimeError('Finish the customer session first')
    for name in ('/dev/ttyUSB0', '/dev/gpiochip0', '/dev/i2c-7'):
        if not Path(name).is_char_device():
            raise RuntimeError('Required hardware is missing: ' + name)
    subprocess.run(['/bin/sh', str(ROOT / 'deploy/apply-device-profile.sh')], check=True)


if __name__ == '__main__':
    apply()
