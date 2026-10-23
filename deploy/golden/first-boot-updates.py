#!/usr/bin/env python3
"""Provision updater on an uncommissioned clone, using only bundled dependencies."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

APP=Path('/opt/sammoy/sammoy2')
FACTORY=Path('/opt/labrix-factory')
STATE=Path('/var/lib/sammoy2')
CONFIG=Path('/etc/labrix-updates')
STORE=Path('/var/lib/labrix-updates')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()


def initialize_bill_filter():
    sys.path.insert(0,str(APP/'services/io-helper'))
    from pulse_journal import PulseJournal
    from bill_filter import normalize
    path=APP/'data/io-helper/nv9.sqlite3'
    settings=normalize({'min_pulse_ms':25,'min_gap_ms':25})
    journal=PulseJournal(path)
    try:
        if journal.value()!=0:raise RuntimeError('Factory cash journal already has pulses')
        old=journal.get_setting('bill_filter')
        if old is not None and old!=settings:raise RuntimeError('Existing bill filter differs')
        if old is None:journal.set_setting('bill_filter',settings)
    finally:journal.close()


def initialize():
    if (STATE/'updates-ready').exists():return
    if not (STATE/'factory-pending').is_file() or not (APP/'GOLDEN_TEMPLATE.json').is_file():
        raise RuntimeError('Not a fresh factory clone')
    if not (STATE/'images-ready').is_file():raise RuntimeError('Offline images not ready')
    if b'radxa,cubie-a7a' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0') or os.uname().machine!='aarch64':
        raise RuntimeError('Unsupported board')
    config=json.loads((FACTORY/'updates.json').read_text())
    if config.get('format')!=1:raise RuntimeError('Unknown factory updater manifest')
    for name,expected in config['files'].items():
        p=FACTORY/name
        if name.startswith('/') or '..' in Path(name).parts or p.is_symlink() or digest(p)!=expected:
            raise RuntimeError('Factory updater file mismatch')
    debs=sorted((FACTORY/'update-debs').glob('*.deb'))
    if not debs or set('update-debs/'+p.name for p in debs)!={n for n in config['files'] if n.startswith('update-debs/')}:
        raise RuntimeError('Dependency package set mismatch')
    subprocess.run(['dpkg','-i',*map(str,debs)],check=True)
    sys.path.insert(0,str(APP/'deploy'))
    from update_protocol import verify_release
    envelope=json.loads((FACTORY/'baseline-release.json').read_text())
    # This authenticates an already embedded baseline, not a newly downloaded update.
    # Verify at its signed issue time so an older shelf image can still be installed offline.
    issued=datetime.fromisoformat(envelope['manifest']['issued_at'].replace('Z','+00:00'))
    public=(FACTORY/'update-signing.pub.pem').read_bytes()
    m=verify_release(envelope,public,now=issued)
    if m['release_no']!=config['release_no'] or m['version']!=config['version']:raise RuntimeError('Baseline release mismatch')
    loaded=json.loads((STATE/'image-configs.json').read_text())
    for service,expected in m['services'].items():
        tag='sammoy2-'+service+':latest';entry=loaded[tag]
        if entry['config']!=expected:raise RuntimeError('Embedded application differs from signed baseline')
        actual=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
        if actual['Id']!=entry['native'] or actual['Architecture']!='arm64':raise RuntimeError('Loaded baseline differs')
    CONFIG.mkdir(parents=True,exist_ok=True);CONFIG.chmod(0o755)
    key=CONFIG/'signing.pub.pem'
    if key.exists() and key.read_bytes()!=public:raise RuntimeError('Refusing trust key replacement')
    key.write_bytes(public);key.chmod(0o644)
    (CONFIG/'hardware').write_text('cubie-a7a\n')
    token=CONFIG/'agent.token'
    if not token.exists():
        fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
    if token.is_symlink() or not token.is_file():raise RuntimeError('Unsafe updater token')
    token.chmod(0o600)
    STORE.mkdir(parents=True,exist_ok=True);STORE.chmod(0o700)
    installed=STORE/'installed.json'
    value={'release_no':m['release_no'],'version':m['version'],'installed_at':time.time(),'origin':'golden-v4'}
    if installed.exists():
        old=json.loads(installed.read_text())
        if old.get('release_no')!=m['release_no']:raise RuntimeError('Existing updater state differs')
    else:
        fd=os.open(installed,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
    initialize_bill_filter()
    (STATE/'updates-ready').write_text('1\n')
    print('Factory updater ready; baseline '+m['version']+'; credentials generated locally.')

if __name__=='__main__':initialize()
