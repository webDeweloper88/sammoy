#!/usr/bin/env python3
"""Update only a verified, unbooted V4 WORK; export a separate V4 card image."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tarfile
import shutil
import signal
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('builder', HERE/'Build-GoldenImage.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
WORK = Path('/var/lib/labrix-golden-build-v2')
IMAGE = WORK/'LABRIX-WORK.img'
OUTPUT = Path('/mnt/g/001_sammoy/LABRIX-CUBIE-A7A-GOLDEN-V4-20261023.img')
PREVIOUS_RELEASE = 'cbbdd507f97a147fe7a998b3840d63ae2555e94002e825c35a3493f3ffa5432c'
EXPECTED_RELEASE = '0c195aa8e3fa33181528161a8ace4e687e2b2c77edad943a236dbf1558b8ba5f'
EXPECTED_SOURCE = 'e911ea253c0441b0456fe8fadfba921b93ec6e1f4aa16eea65b720035b87b59b'
SIZE = 17529044992


def verify_release(release):
    release = Path(release)
    if builder.clean.sha(release/'release.json') != EXPECTED_RELEASE:
        raise RuntimeError('V4 release checksum mismatch')
    manifest = json.loads((release/'release.json').read_text())
    names = {'application.tar.gz','images.tar.gz','images.json','installer.pub','update-deps.tar.gz','update-signing.pub.pem','baseline-release.json'}
    if manifest.get('state') != 'CLEAN_ARM64_APPLICATION_RELEASE' or set(manifest['files']) != names:
        raise RuntimeError('Unexpected application release')
    for name, expected in manifest['files'].items():
        p = release/name
        if p.is_symlink() or builder.clean.sha(p) != expected:
            raise RuntimeError('Release file mismatch: '+name)
    return manifest


def factory_app(root):
    tree = builder.clean.Tree(root)
    app = tree.path('opt/sammoy/sammoy2')
    for rel in ('var/lib/sammoy2/factory-pending','opt/sammoy/sammoy2/GOLDEN_TEMPLATE.json'):
        p = tree.path(rel)
        if p.is_symlink() or not p.is_file():raise RuntimeError('Unbooted factory marker missing')
    for name in ('.env','.factory-identity-ready','factory-access.json'):
        if os.path.lexists(app/name):raise RuntimeError('Image already initialized; refusing changes')
    for name in ('os-identity-ready','images-ready'):
        if os.path.lexists(tree.path('var/lib/sammoy2/'+name)):
            raise RuntimeError('Factory image was already booted')
    data = app/'data'
    if data.exists():
        for p in [data,*data.rglob('*')]:
            if p.is_symlink() or not p.is_dir():raise RuntimeError('Application data present')
    if (app/'.hardware-profile').is_symlink() or (app/'.hardware-profile').read_text().strip() != 'factory-only':
        raise RuntimeError('Hardware profile already applied')
    if builder.clean.sha(tree.path('opt/labrix-factory/release.json')) != PREVIOUS_RELEASE:
        raise RuntimeError('Unexpected previous factory release')
    return tree,app


def replace_release(root, release):
    """Guard all old state before any write; replace application only, never OS."""
    tree,app = factory_app(root)
    stage = tree.path('opt/sammoy/sammoy2.v4-new')
    old = tree.path('opt/sammoy/sammoy2.before-v4')
    if os.path.lexists(stage) or os.path.lexists(old):raise RuntimeError('Previous interrupted upgrade exists')
    identity = release/'application.tar.gz'
    factory = tree.path('opt/labrix-factory')
    for name in ('images.tar.gz','images.json','release.json'):
        if os.path.lexists(factory/(name+'.v4-new')):raise RuntimeError('Staged factory file already exists')
    builder.clean.extract_application(identity,stage)
    replacement = (stage/'deploy/golden/identity.py').read_bytes()
    if b"DEFAULT_OWNER_PASSWORD = 'labrix'" not in replacement or b"DEFAULT_ADMIN_PASSWORD = 'labrix'" not in replacement:
        raise RuntimeError('Expected labrix first-login defaults')
    compile(replacement,'identity.py','exec')
    if 'management-' not in (stage/'services/wash-engine/app/wallet_management.py').read_text():
        raise RuntimeError('Wallet management implementation missing')
    (stage/'.hardware-profile').write_text('factory-only\n')
    (stage/'.hardware-profile').chmod(0o644)
    for name in ('images.tar.gz','images.json','release.json'):
        target=factory/(name+'.v4-new')
        with (release/name).open('rb') as src,target.open('xb') as dst:
            shutil.copyfileobj(src,dst,1024**2);dst.flush();os.fsync(dst.fileno())
        target.chmod(0o600)
        if builder.clean.sha(target)!=builder.clean.sha(release/name):raise RuntimeError('Staged copy differs')
    app.rename(old);stage.rename(app)
    for name in ('images.tar.gz','images.json','release.json'):
        os.replace(factory/(name+'.v4-new'),factory/name)
    shutil.rmtree(old)
    install_updater(root,release)
    return {'application_updated':True,'hardware_profile':'factory-only','database_included':False,'software_updates':True,'bill_sampler_process':True,'nfc_phone_protection':True,'baseline_version':'2026.10.23.2'}


def install_updater(root,release):
    tree=builder.clean.Tree(root)
    factory=tree.path('opt/labrix-factory')
    deps=factory/'update-debs'
    if os.path.lexists(deps):raise RuntimeError('Existing offline updater dependency directory')
    deps.mkdir(mode=0o700)
    with tarfile.open(release/'update-deps.tar.gz','r:gz') as tar:
        members=tar.getmembers()
        if not members or any(not m.isfile() or '/' in m.name or not m.name.endswith('.deb') or m.size>4*1024**2 for m in members):raise RuntimeError('Unsafe dependency archive')
        if len({m.name for m in members})!=len(members):raise RuntimeError('Duplicate dependency package')
        for m in members:
            with tar.extractfile(m) as src,(deps/m.name).open('xb') as dst:shutil.copyfileobj(src,dst)
    for name in ('update-signing.pub.pem','baseline-release.json'):
        shutil.copyfile(release/name,factory/name);(factory/name).chmod(0o644)
    files={n:builder.clean.sha(factory/n) for n in ('update-signing.pub.pem','baseline-release.json')}
    files.update({'update-debs/'+p.name:builder.clean.sha(p) for p in deps.iterdir()})
    (factory/'updates.json').write_text(json.dumps({'format':1,'release_no':2,'version':'2026.10.23.2','files':files},indent=2)+'\n')
    app=tree.path('opt/sammoy/sammoy2')
    units=('sammoy2-factory-updates.service','sammoy2-software-updates.service','sammoy2-update-cleanup.service','sammoy2-update-cleanup.timer')
    for unit in units:
        source=app/'deploy'/('golden/' if unit.startswith('sammoy2-factory-') else '')/unit
        tree.write('etc/systemd/system/'+unit,source.read_text())
    for unit in ('sammoy2-post.service','sammoy2-factory-app.service','sammoy2-software-updates.service'):
        tree.write('etc/systemd/system/'+unit+'.d/factory-updates.conf','[Unit]\nRequires=sammoy2-factory-updates.service\nAfter=sammoy2-factory-updates.service\n')
    for unit in ('sammoy2-factory-updates.service','sammoy2-software-updates.service'):
        folder=tree.directory('etc/systemd/system/multi-user.target.wants');p=folder/unit
        if os.path.lexists(p):raise RuntimeError('Updater unit already enabled')
        p.symlink_to('/etc/systemd/system/'+unit)
    folder=tree.directory('etc/systemd/system/timers.target.wants')
    (folder/'sammoy2-update-cleanup.timer').symlink_to('/etc/systemd/system/sammoy2-update-cleanup.timer')
    tree.directory('etc/labrix-updates',mode=0o755)
    tree.write('etc/labrix-updates/signing.pub.pem',(release/'update-signing.pub.pem').read_text())
    tree.write('etc/labrix-updates/hardware','cubie-a7a\n')
    for name in ('agent.token','installed.json'):
        p=tree.path(('etc/labrix-updates/' if name=='agent.token' else 'var/lib/labrix-updates/')+name)
        if os.path.lexists(p):raise RuntimeError('Updater identity already exists')


def rebuild():
    if os.geteuid()!=0:raise RuntimeError('WSL root required')
    if WORK.is_symlink() or IMAGE.is_symlink():raise RuntimeError('Unsafe working path')
    manifest_file=WORK/'working-copy.json'
    manifest=json.loads(manifest_file.read_text())
    if (manifest.get('state')!='EXPORTED_GOLDEN_CANDIDATE' or not manifest.get('sanitized')
        or not manifest.get('shrunk') or not manifest.get('source_unchanged')
        or manifest.get('release_sha256')!=PREVIOUS_RELEASE):
        raise RuntimeError('Expected completed, never-booted V3 working candidate; no changes made')
    # V3 preparation records the original card hash under source_sha256.
    if manifest.get('source_sha256')!=EXPECTED_SOURCE:raise RuntimeError('Unexpected source provenance')
    if IMAGE.stat().st_size!=SIZE:raise RuntimeError('Unexpected V3 WORK size')
    for suffix in ('','.partial','.json','.sha256'):
        if os.path.lexists(str(OUTPUT)+suffix):raise RuntimeError('V4 output exists; refusing overwrite')
    if shutil.disk_usage(OUTPUT.parent).free<SIZE+1024**3:raise RuntimeError('Need 18 GiB free on G:')
    if shutil.disk_usage(WORK).free<2*1024**3:raise RuntimeError('Need 2 GiB free in Ubuntu')
    release=HERE/'release';verify_release(release)
    if builder.run('losetup','-j',str(IMAGE)):raise RuntimeError('WORK already attached')
    table=json.loads(builder.run('sfdisk','--json',str(IMAGE)))['partitiontable']
    layout=[(p['start'],p['size']) for p in table['partitions']]
    if table.get('label')!='gpt' or table.get('sectorsize')!=512 or layout!=[(32768,32768),(65536,614400),(679936,33554432)]:
        raise RuntimeError('Unexpected V3 partition geometry')
    print('Verifying private WORK image. Original and all old IMG exports stay untouched...',flush=True)
    if builder.clean.sha(IMAGE)!=manifest.get('export_sha256'):raise RuntimeError('WORK changed since verified export')
    boot_hash=builder.clean.boot_prefix_sha(IMAGE)
    builder.WORK=WORK;builder.IMAGE=IMAGE
    tool=builder.zero_tool()
    mount=Path('/mnt/labrix-application-v4')
    if os.path.lexists(mount):raise RuntimeError('Mount path exists')
    backup=WORK/'working-copy.before-v4.json'
    if backup.exists():raise RuntimeError('V4 preparation was already attempted; stop for inspection')
    # Validate factory state read-only before recording any mutation state.
    with builder.root_loop(IMAGE,679936,16*1024**3) as loop:
        mount.mkdir(mode=0o700)
        try:
            subprocess.run(['mount','-o','ro,noload,nosuid,nodev,noexec',loop,str(mount)],check=True)
            try:factory_app(mount)
            finally:subprocess.run(['umount',str(mount)],check=True)
        finally:mount.rmdir()
    with backup.open('x') as f:json.dump(manifest,f,indent=2)
    manifest['state']='UPDATING_APPLICATION_V4'
    manifest_file.write_text(json.dumps(manifest,indent=2)+'\n')
    with builder.root_loop(IMAGE,679936,16*1024**3) as loop:
        builder.fsck(loop);mount.mkdir(mode=0o700)
        try:
            subprocess.run(['mount','-o','rw,nosuid,nodev,noexec',loop,str(mount)],check=True)
            try:
                if shutil.disk_usage(mount).free<2*1024**3:raise RuntimeError('Insufficient image filesystem space')
                report=replace_release(mount,release)
            finally:subprocess.run(['umount',str(mount)],check=True)
        finally:
            if subprocess.run(['findmnt','-rn','-S',loop],stdout=subprocess.DEVNULL).returncode!=0:mount.rmdir()
        builder.fsck(loop);builder.zero_free(loop,mount,tool=tool);builder.fsck(loop)
    if builder.clean.boot_prefix_sha(IMAGE)!=boot_hash:raise RuntimeError('Boot prefix changed; do not flash')
    checksum=builder.export(IMAGE,OUTPUT)
    report.update(state='GOLDEN_CANDIDATE_READY_TO_FLASH',board='Radxa Cubie A7A',
        sha256=checksum,bytes=OUTPUT.stat().st_size,sanitized=True,shrunk=True,free_blocks_zeroed=True,
        source_untouched=True,old_exports_untouched=True,first_boot_tested_on_new_board=False,
        setup='/install',ethernet='DHCP',display='HDMI-1/right',auto_expand_on_new_card=True,
        initial_logins='owner / labrix; admin / labrix',must_change_password=True,
        wallet_management_protocol=1,saved_peer_address_fix=True)
    Path(str(OUTPUT)+'.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest.update(state='EXPORTED_GOLDEN_CANDIDATE',export_sha256=checksum,
                    release_sha256=EXPECTED_RELEASE,application_revision='updates-v4',
                    defaults_revision='labrix-first-login')
    manifest_file.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    print('IMAGE READY TO FLASH: G:\\001_sammoy\\'+OUTPUT.name,flush=True)


if __name__=='__main__':
    def interrupted(signum,frame):raise SystemExit('Interrupted; stop and send output')
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,interrupted)
    rebuild()
