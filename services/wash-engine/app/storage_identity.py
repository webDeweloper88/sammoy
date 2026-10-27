"""CL3566 eMMC identity, explicitly versioned; no legacy hash changes.

The existing API's microsd_cid_hash is a historical wire name for storage CID.
New hash domain separation binds all three opaque hashes to the v1 eMMC scheme.
"""
import hashlib
import json
from pathlib import Path
import re

SCHEME = 'cl3566-emmc-v1'


def selected_board(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Invalid board profile symlink')
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ValueError('Invalid board profile record')
    if type(record.get('schema')) is not int or record['schema'] != 1 or record.get('confirmed') is not True:
        raise ValueError('Unconfirmed board profile')
    board = record.get('board_id')
    if board not in ('cubie-a7a', 'cl3566-a-e'):
        raise ValueError('Unknown board profile')
    return board


def emmc_cid(roots):
    # Prefer host sysfs over container /sys. Never combine different roots.
    for root in map(Path, roots):
        if not root.is_dir():
            continue
        candidates = []
        for node in root.glob('mmcblk*'):
            if not re.fullmatch(r'mmcblk[0-9]+', node.name):
                continue
            try:
                kind = (node / 'device/type').read_text().strip()
                removable = (node / 'removable').read_text().strip()
            except FileNotFoundError:
                continue
            if kind == 'MMC' and removable == '0':
                cid = (node / 'device/cid').read_text().strip().lower()
                if not re.fullmatch(r'[0-9a-f]{32}', cid) or cid in ('0' * 32, 'f' * 32):
                    raise ValueError('Invalid eMMC CID')
                candidates.append(cid)
        if len(candidates) != 1:
            raise ValueError('Expected exactly one non-removable MMC device')
        return candidates[0]
    raise ValueError('eMMC sysfs is unavailable')


def cl3566_identity(config, wlan, roots):
    cid = emmc_cid(roots)
    wlan = wlan.strip().lower().replace(':', '')
    if not re.fullmatch(r'[0-9a-f]{12}', wlan) or wlan in ('0' * 12, 'f' * 12):
        raise ValueError('WLAN identity is unavailable')
    prefix = f"{str(config.get('site_code') or '').strip()}:{int(config.get('post_no') or 1)}"
    def digest(kind, value):
        return hashlib.sha256(f'{prefix}:{SCHEME}:{kind}:{value}'.encode()).hexdigest()
    return {'complete': True, 'identity_scheme': SCHEME, 'storage_type': 'emmc',
            'wlan0_mac_present': True, 'microsd_cid_present': False,
            'emmc_cid_present': True, 'wlan0_mac_tail': wlan[-6:],
            'microsd_cid_tail': '', 'emmc_cid_tail': cid[-8:],
            'hardware_fingerprint_hash': digest('hardware_fingerprint', f'{wlan}:{cid}'),
            'wlan0_mac_hash': digest('wlan0_mac', wlan),
            'microsd_cid_hash': digest('emmc_cid', cid)}
