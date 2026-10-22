#!/usr/bin/env python3
"""One-run cleanup, ext4/GPT shrink, free-block scrub and verified .img export."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('clean_copy', HERE / 'Clean-WorkingCopy.py')
clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean)
WORK = Path('/var/lib/labrix-golden-build')
IMAGE = WORK / 'LABRIX-WORK.img'
ROOT_START = 679936
ROOT_BYTES = 16 * 1024**3
NAME = 'LABRIX-CUBIE-A7A-GOLDEN-V2-20261021.img'


def run(*args):
    return subprocess.check_output(args, text=True, env={**os.environ, 'LC_ALL': 'C'}).strip()


def write_gpt(*args):
    # Moving the backup header after truncation emits expected old-size/CRC
    # diagnostics before repairing them. Report only the final verified state;
    # any nonzero exit still exposes the complete diagnostic for investigation.
    result = subprocess.run(['sgdisk', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('GPT operation failed: ' + result.stdout + result.stderr)


def region_sha(path, offset, length):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        stream.seek(offset)
        while length:
            block = stream.read(min(8 * 1024**2, length))
            if not block:
                raise RuntimeError('Image range truncated')
            h.update(block); length -= len(block)
    return h.hexdigest()


@contextmanager
def root_loop(image, start, size):
    loop = run('losetup', '--find', '--show', '--offset', str(start * 512),
               '--sizelimit', str(size), str(image))
    try:
        yield loop
    finally:
        if subprocess.run(['findmnt', '-rn', '-S', loop], stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('Loop still mounted; refusing detach')
        subprocess.run(['losetup', '--detach', loop], check=True)


def fsck(loop):
    rc = subprocess.run(['e2fsck', '-f', '-p', loop]).returncode
    if rc not in (0, 1):
        raise RuntimeError('Offline filesystem check requires review')


def zero_tool():
    bundled = HERE / 'zerofree-amd64'
    if bundled.is_file():
        if os.uname().machine != 'x86_64' or clean.sha(bundled) != '56fd5b07d9fef76aea5f73ace41f60086253ec384dc3c6f21d12a4cbd19facd4':
            raise RuntimeError('Bundled zerofree architecture/hash mismatch')
        tools = WORK / 'tools'
        if tools.is_symlink():
            raise RuntimeError('Unsafe tools directory')
        tools.mkdir(mode=0o700, exist_ok=True)
        target = tools / 'zerofree-amd64'
        if target.is_symlink():
            raise RuntimeError('Unsafe tool path')
        if not target.exists():
            with target.open('xb') as dst, bundled.open('rb') as src:
                shutil.copyfileobj(src, dst)
        if clean.sha(target) != clean.sha(bundled):
            raise RuntimeError('Existing tool hash mismatch')
        target.chmod(0o700)
        return str(target)
    installed = shutil.which('zerofree')
    if not installed:
        raise RuntimeError('Offline zerofree tool missing. Use the updated image-preparation package.')
    return installed


def remove_stale_zero_file(loop, mount):
    if mount.exists() or mount.is_symlink():
        raise RuntimeError('Scrub mountpoint already exists')
    mount.mkdir(mode=0o700)
    mounted = False
    try:
        subprocess.run(['mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid,noexec', loop, str(mount)], check=True)
        mounted = True
        target = mount / '.labrix-zero-free'
        if os.path.lexists(target):
            st = target.lstat()
            import stat
            if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_size > ROOT_BYTES:
                raise RuntimeError('Unexpected leftover scrub file; refusing deletion')
            target.unlink()
            print('Removed only the interrupted temporary zero-fill file.', flush=True)
        subprocess.run(['sync', '-f', str(mount)], check=True)
    finally:
        if mounted:
            subprocess.run(['umount', str(mount)], check=True)
        mount.rmdir()


def zero_free(loop, mount, tool=None):
    # Operate on the unmounted block bitmap, including reserved free blocks.
    # Do not allocate a temporary file or rely on statvfs after ENOSPC.
    if subprocess.run(['findmnt', '-rn', '-S', loop], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Free-block scrubbing requires an unmounted filesystem')
    tool = tool or zero_tool()
    print('Zeroing unallocated ext4 blocks offline...', flush=True)
    subprocess.run([tool, '-v', loop], check=True)
    print('Verifying that all free blocks are zero...', flush=True)
    verified = subprocess.run([tool, '-n', '-v', loop], text=True, stdout=subprocess.PIPE, check=True)
    values = re.findall(r'(\d+)/(\d+)/(\d+)', verified.stdout)
    if len(values) != 1 or int(values[0][0]) != 0:
        raise RuntimeError('Some free blocks are still nonzero; export refused')
    print('All free ext4 blocks zeroed and verified.', flush=True)


def shrink_and_scrub(image, root_bytes=ROOT_BYTES, mount=Path('/mnt/labrix-scrub-root')):
    if image.is_symlink() or not image.is_file() or root_bytes % (1024**2):
        raise RuntimeError('Regular image and whole-MiB filesystem required')
    if run('losetup', '-j', str(image)):
        raise RuntimeError('Image already attached')
    before = json.loads(run('sfdisk', '--json', str(image)))['partitiontable']
    parts = before['partitions']
    if before['label'] != 'gpt' or before['sectorsize'] != 512 or len(parts) != 3 or parts[2]['start'] != ROOT_START:
        raise RuntimeError('Unexpected factory image layout')
    old = parts[2]
    attributes = re.search(r'Attribute flags:\s*([0-9A-Fa-f]{16})', run('sgdisk', '--info=3', str(image)))
    if not attributes:
        raise RuntimeError('Cannot read root GPT attributes')
    attributes = int(attributes.group(1), 16)
    if root_bytes >= old['size'] * 512:
        raise RuntimeError('New filesystem must be smaller than source')
    # GPT sectors 0..33 must change; preserve all bootloader/config/EFI bytes
    # between the GPT and the root partition exactly.
    boot_hash = region_sha(image, 34 * 512, ROOT_START * 512 - 34 * 512)
    with root_loop(image, ROOT_START, old['size'] * 512) as loop:
        fsck(loop)
        filesystem_uuid = run('blkid', '-s', 'UUID', '-o', 'value', loop)
        subprocess.run(['resize2fs', loop, str(root_bytes // 1024**2) + 'M'], check=True)
        fsck(loop)
    end = ROOT_START + root_bytes // 512 - 1
    write_gpt('--delete=3', f'--new=3:{ROOT_START}:{end}',
                    '--typecode=3:' + old['type'], '--partition-guid=3:' + old['uuid'],
                    '--change-name=3:' + old.get('name', ''),
                    *[f'--attributes=3:set:{bit}' for bit in range(64) if attributes & (1 << bit)], str(image))
    size = math.ceil(((end + 1) * 512 + 33 * 512) / 1024**2) * 1024**2
    with image.open('r+b') as stream:
        stream.truncate(size)
    write_gpt('--move-second-header', str(image))
    verified = run('sgdisk', '--verify', str(image))
    if 'No problems found.' not in verified:
        raise RuntimeError('Final GPT validation uncertain: ' + verified)
    print('Reduced GPT verified.', flush=True)
    after = json.loads(run('sfdisk', '--json', str(image)))['partitiontable']
    if after['id'] != before['id']:
        raise RuntimeError('Disk GUID changed')
    # sfdisk node names can change with the filename; compare real metadata.
    for a, b in zip(parts, after['partitions']):
        for field in ('start', 'type', 'uuid', 'name', 'attrs'):
            if a.get(field) != b.get(field):
                raise RuntimeError('Partition metadata changed: ' + field)
    if [p['size'] for p in after['partitions']] != [parts[0]['size'], parts[1]['size'], root_bytes // 512]:
        raise RuntimeError('Partition lengths incorrect')
    if region_sha(image, 34 * 512, ROOT_START * 512 - 34 * 512) != boot_hash:
        raise RuntimeError('Bootloader/config/EFI bytes changed')
    print('Zeroing deleted private data in the reduced filesystem...', flush=True)
    with root_loop(image, ROOT_START, root_bytes) as loop:
        if run('blkid', '-s', 'UUID', '-o', 'value', loop) != filesystem_uuid:
            raise RuntimeError('Root filesystem UUID changed')
        fsck(loop)
        zero_free(loop, mount)
        fsck(loop)
    # Punch only already-zero ranges; this does not change image contents.
    if shutil.which('fallocate'):
        subprocess.run(['fallocate', '--dig-holes', str(image)], check=True)
    return {'logical_bytes': size, 'root_filesystem_bytes': root_bytes,
            'free_blocks_zeroed': True, 'bootloader_config_efi_unchanged': True,
            'disk_guid_preserved': True, 'filesystem_uuid_preserved': True}


def export(image, destination):
    destination = Path(destination)
    partial = Path(str(destination) + '.partial')
    if any(os.path.lexists(p) for p in (destination, partial, Path(str(destination) + '.json'), Path(str(destination) + '.sha256'))):
        raise RuntimeError('Export already exists; refusing overwrite')
    if shutil.disk_usage(destination.parent).free < image.stat().st_size + 1024**3:
        raise RuntimeError('Not enough free space on export drive')
    expected = hashlib.sha256(); done = 0; last = 0
    print('Exporting ready-to-flash image to Windows...', flush=True)
    with image.open('rb') as src, partial.open('xb') as dst:
        for block in iter(lambda: src.read(8 * 1024**2), b''):
            expected.update(block); dst.write(block); done += len(block)
            if time.monotonic() - last >= 5:
                print(f'  Exported {done / 1024**3:.2f} / {image.stat().st_size / 1024**3:.2f} GiB', flush=True)
                last = time.monotonic()
        dst.flush(); os.fsync(dst.fileno())
    print('Verifying exported image SHA-256...', flush=True)
    if partial.stat().st_size != image.stat().st_size or clean.sha(partial) != expected.hexdigest():
        raise RuntimeError('Export verification failed; partial retained')
    partial.rename(destination)
    Path(str(destination) + '.sha256').write_text(expected.hexdigest() + '  ' + destination.name + '\n')
    return expected.hexdigest()


def build(release, output):
    release = Path(release).resolve(); output = Path(output)
    if os.geteuid() != 0 or output.name != NAME or not str(output).startswith('/mnt/g/'):
        raise RuntimeError('WSL root and the planned G: output required')
    state_path = WORK / 'working-copy.json'
    manifest = json.loads(state_path.read_text())
    if manifest['state'] in ('VERIFIED_PRIVATE_WORKING_COPY_NOT_GOLDEN', 'SANITIZED_NOT_SHRUNK_NOT_GOLDEN'):
        zero_tool()  # Fail before mutating the copy when the offline tool is absent.
    if manifest['state'] == 'VERIFIED_PRIVATE_WORKING_COPY_NOT_GOLDEN':
        clean.clean(release)
        manifest = json.loads(state_path.read_text())
    if manifest['state'] == 'SANITIZED_NOT_SHRUNK_NOT_GOLDEN':
        if manifest['release_sha256'] != clean.sha(release / 'release.json'):
            raise RuntimeError('Release changed after sanitation')
        manifest['state'] = 'FINALIZING_WORKING_COPY'
        state_path.write_text(json.dumps(manifest, indent=2) + '\n')
        report = shrink_and_scrub(IMAGE)
        manifest.update(state='SCRUBBED_SHRUNK_READY_FOR_EXPORT', shrunk=True, **report)
        state_path.write_text(json.dumps(manifest, indent=2) + '\n')
    if manifest['state'] != 'SCRUBBED_SHRUNK_READY_FOR_EXPORT':
        raise RuntimeError('Unexpected state; stop and send this output, do not retry')
    checksum = export(IMAGE, output)
    report = {'state': 'GOLDEN_CANDIDATE_READY_TO_FLASH', 'board': 'Radxa Cubie A7A',
              'sha256': checksum, 'bytes': output.stat().st_size,
              'sanitized': True, 'shrunk': True, 'free_blocks_zeroed': True,
              'source_untouched': True, 'first_boot_tested_on_new_board': False,
              'setup': '/install', 'ethernet': 'DHCP', 'display': 'HDMI-1/right',
              'auto_expand_on_new_card': True}
    Path(str(output) + '.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest['state'] = 'EXPORTED_GOLDEN_CANDIDATE'; manifest['export_sha256'] = checksum
    state_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    print('IMAGE READY TO FLASH: G:\\001_sammoy\\' + NAME, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    build(args.release, args.output)
