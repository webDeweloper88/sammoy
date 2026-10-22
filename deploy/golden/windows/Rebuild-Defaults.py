#!/usr/bin/env python3
"""Revise only a verified, never-booted V2 WORK candidate; preserve old exports."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('builder', HERE/'Build-GoldenImage.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
WORK = Path('/var/lib/labrix-golden-build-v2')
IMAGE = WORK/'LABRIX-WORK.img'
OUTPUT = Path('/mnt/g/001_sammoy/LABRIX-CUBIE-A7A-GOLDEN-V2-LABRIX-20261021.img')
PREVIOUS_RELEASE = 'e80ce98d9ca7abc86d76148f6a2e533593ef16e77b6a06a0c2382d9cb2bd83f4'
PREVIOUS_IDENTITY = '3a06a03b46bf92e66da5f36c581fd11d6992c46519afb9a0c5f385a57674681f'


def replace_identity(root, replacement):
    root=Path(root)
    for relative in ('var/lib/sammoy2/factory-pending', 'opt/sammoy/sammoy2/GOLDEN_TEMPLATE.json'):
        if not (root/relative).is_file():raise RuntimeError('Uninitialized factory marker missing')
    app=root/'opt/sammoy/sammoy2'
    for name in ('.env','.factory-identity-ready','factory-access.json'):
        if os.path.lexists(app/name):raise RuntimeError('Working image already initialized; refusing changes')
    pg=app/'data/postgres'
    if pg.exists() and (pg.is_symlink() or any(pg.iterdir())):
        raise RuntimeError('Database data present; refusing changes')
    target=app/'deploy/golden/identity.py'
    if target.is_symlink() or builder.clean.sha(target)!=PREVIOUS_IDENTITY:
        raise RuntimeError('Unexpected factory identity script')
    if b"DEFAULT_OWNER_PASSWORD = 'labrix'" not in replacement or b"DEFAULT_ADMIN_PASSWORD = 'labrix'" not in replacement:
        raise RuntimeError('Default password revision differs')
    compile(replacement,'identity.py','exec')
    temporary=target.with_name('identity.py.defaults-new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(replacement);stream.flush();os.fsync(stream.fileno())
    temporary.chmod(target.stat().st_mode&0o777)
    os.replace(temporary,target)


def rebuild():
    if os.geteuid()!=0:raise RuntimeError('WSL root required')
    if WORK.is_symlink() or IMAGE.is_symlink():raise RuntimeError('Unsafe working path')
    state_file=WORK/'working-copy.json'
    manifest=json.loads(state_file.read_text())
    if (manifest.get('state')!='EXPORTED_GOLDEN_CANDIDATE' or not manifest.get('sanitized')
        or not manifest.get('shrunk') or not manifest.get('source_unchanged')
        or manifest.get('release_sha256')!=PREVIOUS_RELEASE):
        raise RuntimeError('Expected the completed original V2 working candidate; no image changed')
    if IMAGE.stat().st_size!=17529044992:raise RuntimeError('Unexpected image size')
    if any(os.path.lexists(str(OUTPUT)+suffix) for suffix in ('','.partial','.json','.sha256')):
        raise RuntimeError('New output already exists; refusing overwrite')
    if shutil.disk_usage(OUTPUT.parent).free<IMAGE.stat().st_size+1024**3:
        raise RuntimeError('Need 18 GiB free on G:')
    if builder.run('losetup','-j',str(IMAGE)):raise RuntimeError('Working image is already attached')
    table=json.loads(builder.run('sfdisk','--json',str(IMAGE)))['partitiontable']
    if table.get('label')!='gpt' or table.get('sectorsize')!=512 or [(p['start'],p['size']) for p in table['partitions']]!=[(32768,32768),(65536,614400),(679936,33554432)]:
        raise RuntimeError('Unexpected V2 partition layout')
    print('Verifying complete private V2 WORK image; original and old IMG remain untouched...',flush=True)
    if builder.clean.sha(IMAGE)!=manifest.get('export_sha256'):
        raise RuntimeError('WORK image differs from the verified export; no changes made')
    boot_hash=builder.clean.boot_prefix_sha(IMAGE)
    replacement=(HERE/'identity.py').read_bytes()
    tool=builder.zero_tool()
    mount=Path('/mnt/labrix-defaults-v2')
    if os.path.lexists(mount):raise RuntimeError('Mount path already exists')
    backup=WORK/'working-copy.before-defaults.json'
    with backup.open('x') as f:json.dump(manifest,f,indent=2)
    manifest['state']='UPDATING_FACTORY_DEFAULTS'
    state_file.write_text(json.dumps(manifest,indent=2)+'\n')
    with builder.root_loop(IMAGE,679936,16*1024**3) as loop:
        builder.fsck(loop);mount.mkdir(mode=0o700)
        try:
            subprocess.run(['mount','-o','rw,nosuid,nodev,noexec',loop,str(mount)],check=True)
            try:
                replace_identity(mount,replacement)
            finally:
                subprocess.run(['umount',str(mount)],check=True)
        finally:
            if subprocess.run(['findmnt','-rn','-S',loop],stdout=subprocess.DEVNULL).returncode!=0:
                mount.rmdir()
        builder.fsck(loop)
        builder.zero_free(loop,mount,tool=tool)
        builder.fsck(loop)
    if builder.clean.boot_prefix_sha(IMAGE)!=boot_hash:raise RuntimeError('Boot prefix changed; do not flash')
    checksum=builder.export(IMAGE,OUTPUT)
    report={'state':'GOLDEN_CANDIDATE_READY_TO_FLASH','board':'Radxa Cubie A7A',
            'sha256':checksum,'bytes':OUTPUT.stat().st_size,'sanitized':True,'shrunk':True,
            'source_untouched':True,'old_export_untouched':True,'first_boot_tested_on_new_board':False,
            'initial_logins':'owner / labrix; admin / labrix','must_change_password':True}
    Path(str(OUTPUT)+'.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest.update(state='EXPORTED_GOLDEN_CANDIDATE',export_sha256=checksum,
                    defaults_revision='labrix-first-login',identity_script_sha256=hashlib.sha256(replacement).hexdigest())
    state_file.write_text(json.dumps(manifest,indent=2)+'\n')
    print('IMAGE READY TO FLASH: G:\\001_sammoy\\'+OUTPUT.name,flush=True)


if __name__=='__main__':
    def interrupted(signum,frame):raise SystemExit('Interrupted; stop and send this output')
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,interrupted)
    rebuild()
