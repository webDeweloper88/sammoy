#!/usr/bin/env python3
"""Load a verified, application-only image archive on the fresh ARM64 clone."""
import gzip
import shutil
import sys
import tempfile
import hashlib
import json
from pathlib import Path
import subprocess


def load(state=Path('/var/lib/sammoy2'),release=Path('/opt/labrix-factory')):
    ready = state / 'images-ready'
    if ready.is_file():
        return
    if not (state / 'factory-pending').is_file() or not (state / 'os-identity-ready').is_file():
        raise RuntimeError('Factory identity not ready')
    manifest = json.loads((release / 'images.json').read_text())
    archive = release / 'images.tar.gz'
    h = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(chunk)
    if h.hexdigest() != manifest['archive_sha256']:
        raise RuntimeError('Offline Docker archive hash mismatch')
    if set(manifest['images']) != {'postgres:16-alpine', 'sammoy2-wash-engine:latest',
                                   'sammoy2-io-helper:latest', 'sammoy2-kiosk-ui:latest',
                                   'sammoy2-telegram-reports:latest'}:
        raise RuntimeError('Unexpected offline image set')
    refs={}
    if manifest.get('format')==2:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from update_archive import config_references
        # A temporary uncompressed file allows validation before Docker can import anything.
        with tempfile.TemporaryDirectory(prefix='verified-images-',dir=release) as temp:
            unpacked=Path(temp)/'images.tar'
            with gzip.open(archive,'rb') as src,unpacked.open('wb') as dst:shutil.copyfileobj(src,dst,1024**2)
            refs=config_references(unpacked,set(manifest['images'].values()))
            subprocess.run(['docker','load','-i',str(unpacked)],check=True)
    else:
        subprocess.run(['docker', 'load', '-i', str(archive)], check=True)
    loaded={}
    for tag, expected in manifest['images'].items():
        try:actual = json.loads(subprocess.check_output(['docker', 'image', 'inspect', expected], text=True,stderr=subprocess.DEVNULL))[0]
        except subprocess.CalledProcessError:
            if expected not in refs:raise
            actual=json.loads(subprocess.check_output(['docker','image','inspect',refs[expected]],text=True))[0]
        if actual['Id'] not in (expected,refs.get(expected)) or actual['Architecture'] != 'arm64' or actual['Os'] != 'linux':
            raise RuntimeError('Docker image identity/platform mismatch: ' + tag)
        subprocess.run(['docker', 'tag', actual['Id'], tag], check=True)
        loaded[tag]={'config':expected,'native':actual['Id']}
    if manifest.get('format')==2:
        (state/'image-configs.json').write_text(json.dumps(loaded,sort_keys=True))
    ready.write_text('1\n')
    ready.chmod(0o600)
    # No longer needed after all five images are proven. Keep the manifest.
    archive.unlink()


if __name__ == '__main__':
    load()
