#!/usr/bin/env python3
"""Resume the specific interrupted free-block scrub, without redoing sanitation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('builder', HERE / 'Build-GoldenImage.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def validate_layout(source, reduced):
    if source.get('label') != 'gpt' or reduced.get('label') != 'gpt' or source.get('sectorsize') != 512 or reduced.get('sectorsize') != 512:
        raise RuntimeError('Expected GPT/512-byte images')
    if source['id'] != reduced['id'] or len(source['partitions']) != 3 or len(reduced['partitions']) != 3:
        raise RuntimeError('Disk identity or partition count differs')
    if [(p['start'], p['size']) for p in source['partitions']] != [(32768, 32768), (65536, 614400), (679936, 124055519)]:
        raise RuntimeError('Original layout differs from inspected source')
    if [p['size'] for p in reduced['partitions']] != [32768, 614400, builder.ROOT_BYTES // 512]:
        raise RuntimeError('Working copy has not reached the expected 16-GiB shrink stage')
    for a, b in zip(source['partitions'], reduced['partitions']):
        for key in ('start', 'uuid', 'type', 'name', 'attrs'):
            if a.get(key) != b.get(key):
                raise RuntimeError('Partition metadata differs: ' + key)


def recover(release, output):
    release = Path(release).resolve()
    state_file = builder.WORK / 'working-copy.json'
    image = builder.IMAGE
    if os.geteuid() != 0:
        raise RuntimeError('Run as WSL root')
    manifest = json.loads(state_file.read_text())
    if manifest.get('state') != 'FINALIZING_WORKING_COPY' or manifest.get('sanitized') is not True:
        raise RuntimeError('Not the reported interrupted scrub state; no automatic changes made')
    if manifest.get('source_sha256') != builder.clean.EXPECTED_SOURCE:
        raise RuntimeError('Original source fingerprint differs')
    source = Path(manifest['source'])
    if source.is_symlink() or image.is_symlink() or image.stat().st_nlink != 1 or os.path.samefile(source, image):
        raise RuntimeError('Source/working image identity unsafe')
    if image.stat().st_size != 17529044992 or source.stat().st_size != 63864569856:
        raise RuntimeError('Image sizes differ from the interrupted stage')
    if manifest['release_sha256'] != builder.clean.sha(release / 'release.json'):
        raise RuntimeError('Original release folder changed; do not overwrite it')
    output = Path(output)
    if any(os.path.lexists(p) for p in (output, Path(str(output) + '.partial'), Path(str(output) + '.json'), Path(str(output) + '.sha256'))):
        raise RuntimeError('Export already exists; nothing overwritten')
    if builder.run('losetup', '-j', str(image)):
        raise RuntimeError('Working image still attached; stop and send output')
    original_stat = source.stat()
    source_layout = json.loads(builder.run('sfdisk', '--json', str(source)))['partitiontable']
    reduced = json.loads(builder.run('sfdisk', '--json', str(image)))['partitiontable']
    validate_layout(source_layout, reduced)
    if 'No problems found.' not in builder.run('sgdisk', '--verify', str(image)):
        raise RuntimeError('Reduced GPT needs review')
    prefix = builder.region_sha(source, 34 * 512, builder.ROOT_START * 512 - 34 * 512)
    if builder.region_sha(image, 34 * 512, builder.ROOT_START * 512 - 34 * 512) != prefix:
        raise RuntimeError('Bootloader/config/EFI differs from original')
    with source.open('rb') as f:
        f.seek(builder.ROOT_START * 512 + 1024 + 104)
        filesystem_uuid = str(uuid.UUID(bytes=f.read(16)))
    tool = builder.zero_tool()  # Verify bundled binary before changing the image.
    print('Interrupted stage verified. Original is read-only; continuing WORK image only.', flush=True)
    mount = Path('/mnt/labrix-resume-check')
    with builder.root_loop(image, builder.ROOT_START, builder.ROOT_BYTES) as loop:
        if builder.run('blkid', '-s', 'UUID', '-o', 'value', loop) != filesystem_uuid:
            raise RuntimeError('Root filesystem UUID differs from original')
        builder.fsck(loop)
        # Validate the fresh factory state and delete only our interrupted file.
        if mount.exists() or mount.is_symlink():
            raise RuntimeError('Recovery mountpoint already exists')
        mount.mkdir(mode=0o700)
        mounted = False
        try:
            import subprocess
            subprocess.run(['mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid,noexec', loop, str(mount)], check=True)
            mounted = True
            app = mount / 'opt/sammoy/sammoy2'
            if not (app / 'GOLDEN_TEMPLATE.json').is_file() or (app / '.env').exists() or (app / 'data').exists():
                raise RuntimeError('Not an uninitialized clean factory copy')
            if not (mount / 'var/lib/sammoy2/factory-pending').is_file():
                raise RuntimeError('Factory marker missing')
            if list((mount / 'etc/ssh').glob('ssh_host_*')):
                raise RuntimeError('Source SSH host keys unexpectedly present')
            zero = mount / '.labrix-zero-free'
            if os.path.lexists(zero):
                st = zero.lstat()
                if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_size > builder.ROOT_BYTES:
                    raise RuntimeError('Unexpected temporary scrub file')
                zero.unlink()
                print('Removed the interrupted temporary zero-fill file.', flush=True)
            subprocess.run(['sync', '-f', str(mount)], check=True)
        finally:
            if mounted:
                subprocess.run(['umount', str(mount)], check=True)
            mount.rmdir()
        builder.fsck(loop)
        builder.zero_free(loop, mount, tool=tool)
        builder.fsck(loop)
    after = source.stat()
    if (after.st_size, after.st_mtime_ns) != (original_stat.st_size, original_stat.st_mtime_ns):
        raise RuntimeError('Original changed externally; stop and inspect')
    manifest.update(state='SCRUBBED_SHRUNK_READY_FOR_EXPORT', shrunk=True,
                    logical_bytes=image.stat().st_size, root_filesystem_bytes=builder.ROOT_BYTES,
                    free_blocks_zeroed=True, bootloader_config_efi_unchanged=True,
                    disk_guid_preserved=True, filesystem_uuid_preserved=True)
    state_file.write_text(json.dumps(manifest, indent=2) + '\n')
    builder.build(release, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    recover(args.release, args.output)
