#!/usr/bin/env python3
"""Resolve confirmed platform + service layout; no activation side effects."""
from pathlib import Path
import json
import subprocess
import sys
from board_profiles import STATE, load_selection, detect

ROOT = Path('/opt/sammoy/sammoy2')
LAYOUTS = {'full': [], 'factory-only': ['docker-compose.factory.yml'],
           'nfc-relay': ['docker-compose.nfc-relay.yml'],
           'relay-only': ['docker-compose.relay-only.yml'],
           'dry-fog': ['docker-compose.nfc-relay.yml','docker-compose.dry-fog.yml']}


def board(path=STATE):
    selected = load_selection(path)
    return selected['board_id'] if selected else None


def compose(layout, selection=STATE):
    if layout not in LAYOUTS:
        raise ValueError('Unknown service layout')
    selected = board(selection)
    if selected == 'cl3566-a-e' or (selected is None and layout=='factory-only' and detect()['suggested_board']=='cl3566-a-e'):
        if layout == 'relay-only':
            raise ValueError('CL3566 relay-only layout is not supported')
        overlays = ['docker-compose.cl3566.yml']
        if layout == 'dry-fog':
            overlays.append('docker-compose.cl3566-fog.yml')
        if layout == 'factory-only':
            overlays.append('docker-compose.factory.yml')
    else:
        overlays = LAYOUTS[layout]
    return ['docker','compose','-f','docker-compose.yml'] + [x for name in overlays for x in ('-f',name)]


def required_nodes(selection=STATE):
    return ('/dev/ttyS7','/dev/ttyS9') if board(selection)=='cl3566-a-e' else ('/dev/ttyUSB0','/dev/gpiochip0','/dev/i2c-7')


def ready(selection=STATE):
    if not all(Path(name).is_char_device() for name in required_nodes(selection)):
        return False
    if board(selection) == 'cl3566-a-e':
        try:
            return Path('/sys/external_gpio/jwsioc_inout_gpio5').read_text().strip()=='0'
        except OSError:
            return False
    return True


def start():
    # Only explicit CL3566 selection reaches this launcher; legacy start remains intact.
    if board() != 'cl3566-a-e':
        raise RuntimeError('CL3566 selection is not confirmed')
    layout=(ROOT/'.hardware-profile').read_text().strip() if (ROOT/'.hardware-profile').exists() else 'factory-only'
    if layout!='factory-only' and not ready():
        layout='factory-only'
    subprocess.run(compose(layout)+['config','--quiet'],cwd=ROOT,check=True)
    subprocess.run(compose(layout)+['up','-d','--no-build','--pull','never','--wait','--wait-timeout','180'],cwd=ROOT,check=True)


if __name__=='__main__':
    if sys.argv[1:] == ['start']:
        start()
    elif sys.argv[1:] == ['factory']:
        if board() is not None or detect()['suggested_board']!='cl3566-a-e':
            raise SystemExit('Expected an unconfirmed CL3566')
        subprocess.run(compose('factory-only')+['up','-d','--no-build','--pull','never','--wait','--wait-timeout','180'],cwd=ROOT,check=True)
    elif sys.argv[1:] == ['selected']:
        selected=board()
        print(selected or ('cl3566-unconfirmed' if detect()['suggested_board']=='cl3566-a-e' else 'legacy'))
    else:
        raise SystemExit('Usage: board_runtime.py selected|start')
