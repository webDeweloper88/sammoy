#!/usr/bin/env python3
"""Expand only partition 3 of a new Cubie A7A factory card, never shrink."""
import json
from pathlib import Path
import re
import subprocess


def get(*args):
    return subprocess.check_output(args, text=True).strip()


def grow():
    state = Path('/var/lib/sammoy2')
    marker = state / 'grow-pending'
    if not marker.is_file():
        return
    if not Path('/opt/sammoy/sammoy2/GOLDEN_TEMPLATE.json').is_file():
        raise RuntimeError('Golden template missing')
    model = Path('/proc/device-tree/model').read_text().replace('\0', '').lower()
    # The vendor DT in this A7A image reports its SoC name, not the retail board.
    if model != 'sun60iw2' and not ('cubie' in model and 'a7a' in model):
        raise RuntimeError('Automatic expansion is limited to Cubie A7A')
    root = get('findmnt', '-n', '-o', 'SOURCE', '/')
    if not re.fullmatch(r'/dev/mmcblk\d+p3', root) or get('findmnt', '-n', '-o', 'FSTYPE', '/') != 'ext4':
        raise RuntimeError('Expected ext4 root on MMC partition 3')
    disk = root[:-2]
    data = json.loads(get('sfdisk', '--json', disk))['partitiontable']
    parts = data['partitions']
    if data.get('label') != 'gpt' or data.get('sectorsize') != 512 or len(parts) != 3:
        raise RuntimeError('Unexpected factory card partition table')
    if [(p['start'], p['size']) for p in parts[:2]] != [(32768, 32768), (65536, 614400)] or parts[2]['start'] != 679936:
        raise RuntimeError('Factory partition offsets differ')
    total = int(get('blockdev', '--getsize64', disk)) // 512
    desired = total - 33 - parts[2]['start']
    if desired < parts[2]['size']:
        raise RuntimeError('Refusing to shrink a live partition')
    # Move GPT backup from the short image's end to the actual new card's end.
    subprocess.run(['sgdisk', '--move-second-header', disk], check=True)
    if desired > parts[2]['size']:
        # sfdisk -N changes only the selected partition; unspecified UUID/type,
        # name and attributes are retained. Never change its starting sector.
        subprocess.run(['sfdisk', '--no-reread', '--no-tell-kernel', '--force', '-N', '3', disk],
                       input=f'start={parts[2]["start"]}, size={desired}\n', text=True, check=True)
        subprocess.run(['partx', '--update', '--nr', '3', disk], check=True)
    subprocess.run(['resize2fs', root], check=True)
    marker.unlink()
    (state / 'grow-ready').write_text('1\n')
    print('Factory card expanded; boot partitions and root UUID retained.')


if __name__ == '__main__':
    try:
        grow()
    except Exception as exc:
        # A 16-GiB filesystem remains usable if the kernel cannot resize the
        # live partition. Keep the marker for the next boot and allow setup.
        print('Card expansion deferred: ' + str(exc), flush=True)
