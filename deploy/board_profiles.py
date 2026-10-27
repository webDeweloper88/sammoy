#!/usr/bin/env python3
"""Board selection foundation. Detection/confirmation never activates hardware.

Independent of .hardware-profile (service layout), wash/dry_fog and wallet roles.
Uses only stdlib so the host installer can run before application provisioning.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

STATE = Path('/etc/labrix/board-profile.json')
PROFILES = {
    'cubie-a7a': {'id': 'cubie-a7a', 'name': 'Radxa Cubie A7A',
        'modbus': {'device': '/dev/ttyUSB0', 'baud_rate': 9600, 'slave_address': 1},
        'nfc': {'transport': 'i2c', 'bus': 7, 'address': 0x24},
        'bill': {'backend': 'gpiod', 'device': '/dev/gpiochip0', 'line': 33},
        'storage_identity': 'legacy-mmc', 'application_integration': 'legacy'},
    'cl3566-a-e': {'id': 'cl3566-a-e', 'name': 'CL3566-A-E / RK3566',
        'modbus': {'device': '/dev/ttyS7', 'baud_rate': 9600, 'slave_address': 1},
        'nfc': {'transport': 'hsu', 'device': '/dev/ttyS9', 'baud_rate': 115200},
        'bill': {'backend': 'vendor-sysfs', 'logical_io': 5,
                 'mode_path': '/sys/external_gpio/jwsioc_inout_gpio5',
                 'value_path': '/sys/external_gpio/jwsioc_gpio5',
                 'header': 'IO1', 'physical_pin': 8, 'active_low': True},
        'storage_identity': 'emmc-pending', 'application_integration': 'pending'},
}


def profile(board_id):
    if board_id not in PROFILES:
        raise ValueError('Unknown board profile')
    return deepcopy(PROFILES[board_id])


def read_optional(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b''


def detect(root=Path('/')):
    root = Path(root)
    compatible = read_optional(root / 'proc/device-tree/compatible').split(b'\0')
    model = read_optional(root / 'proc/device-tree/model').decode(errors='replace').strip('\0\n')
    cmdline = read_optional(root / 'proc/cmdline').decode(errors='replace')
    evidence = []
    candidates = []
    if b'radxa,cubie-a7a' in compatible:
        candidates.append('cubie-a7a')
        evidence.append('compatible:radxa,cubie-a7a')
    # Generic RK3566/EVB and existence of ttyS7 alone are not model evidence.
    vendor_revision = re.search(r'(?:^|\s)androidboot\.hw_rev=(CL3566-A(?:-E)?-V[0-9.]+)(?:\s|$)', cmdline)
    vendor_driver = (root / 'sys/bus/platform/drivers/jwsioc_gpio/jwsioc_a').exists()
    if vendor_revision and vendor_driver:
        candidates.append('cl3566-a-e')
        evidence += ['vendor_revision:' + vendor_revision.group(1), 'driver:jwsioc_a']
    return {'status': 'suggested' if len(candidates) == 1 else 'ambiguous' if candidates else 'unknown',
            'suggested_board': candidates[0] if len(candidates) == 1 else None,
            'candidates': candidates, 'model': model, 'evidence': evidence}


def validate_selection(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'board_id', 'confirmed', 'confirmed_at', 'method'}:
        raise ValueError('Invalid board selection record')
    if type(value['schema']) is not int or value['schema'] != 1 or value['confirmed'] is not True:
        raise ValueError('Board selection is not confirmed')
    profile(value['board_id'])
    if value['method'] not in ('manual', 'detected-confirmed'):
        raise ValueError('Invalid confirmation method')
    stamp = datetime.fromisoformat(value['confirmed_at'])
    if stamp.tzinfo is None:
        raise ValueError('Confirmation timestamp must include timezone')
    return dict(value)


def load_selection(path=STATE):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Board selection must not be a symlink')
    if not path.exists():
        return None
    return validate_selection(json.loads(path.read_text()))


def confirm(board_id, detection, path=STATE):
    """Persist explicit administrative choice only; no activation or board switching."""
    profile(board_id)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / '.board-profile.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = load_selection(path)
        if existing:
            if existing['board_id'] != board_id:
                raise ValueError('Confirmed board cannot be replaced; separate migration required')
            return existing
        if detection['status'] == 'ambiguous':
            raise ValueError('Conflicting board evidence; resolve before confirmation')
        if detection['suggested_board'] and detection['suggested_board'] != board_id:
            raise ValueError('Selection conflicts with detected board')
        value = {'schema': 1, 'board_id': board_id, 'confirmed': True,
                 'confirmed_at': datetime.now(timezone.utc).isoformat(),
                 'method': 'detected-confirmed' if detection['suggested_board'] else 'manual'}
        fd, temp = tempfile.mkstemp(prefix='.board-profile-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(value, output, indent=2)
                output.write('\n'); output.flush(); os.fsync(output.fileno())
            os.replace(temp, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return value


def inspect(root=Path('/'), path=STATE):
    detection = detect(root)
    selection = load_selection(path)
    return {'schema': 1, 'detection': detection, 'selection': selection,
            'profiles': [profile(name) for name in PROFILES],
            'activation_performed': False,
            'note': 'Selection alone does not prove hardware readiness or permit cash operations.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', choices=sorted(PROFILES))
    args = parser.parse_args()
    if args.confirm:
        if os.geteuid() != 0:
            parser.error('Confirmation requires root')
        confirm(args.confirm, detect())
    print(json.dumps(inspect(), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
