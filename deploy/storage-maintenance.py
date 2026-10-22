#!/usr/bin/python3
"""Bounded disposable-file cleanup. Never touches application data or Docker volumes."""
import argparse
from pathlib import Path
import subprocess
import time

ARCHIVE_DIRS = (Path('/var/cache/sammoy2/updates'), Path('/home/admin/.cache/sammoy-tools'))

def clear_archives(directory, reset=False, now=None):
    now = time.time() if now is None else now
    freed = 0
    # Fixed directories only; never follow a replaced directory or file symlink.
    if directory.is_symlink() or not directory.is_dir():
        return freed
    for item in directory.iterdir():
        if item.is_symlink() or not item.is_file():
            continue
        if not item.name.endswith(('.tar', '.tar.gz', '.tar.xz', '.tgz')):
            continue
        info = item.stat()
        if not reset and now - info.st_mtime < 172800:
            continue
        item.unlink()
        freed += info.st_size
    return freed

def main(reset=False):
    freed = sum(clear_archives(path, reset) for path in ARCHIVE_DIRS)
    # Prune only unused build cache; retained images allow restart and rollback.
    command = ['docker', 'builder', 'prune', '--force', '--keep-storage', '512MB']
    if not reset:
        command += ['--filter', 'until=48h']
    for args in (command, ['apt-get', 'clean']):
        try:
            subprocess.run(args, check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError):
            print('Optional storage cleanup deferred:', args[0], flush=True)
    print('Disposable archives removed (bytes):', freed, flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--reset', action='store_true')
    main(parser.parse_args().reset)
