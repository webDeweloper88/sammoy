#!/usr/bin/env python3
"""Read-only offline inventory of the verified WORK image. No code inside it runs."""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import stat
import subprocess

WORK=Path('/var/lib/labrix-golden-build')
IMAGE=WORK/'LABRIX-WORK.img'


def run(*args):
    return subprocess.check_output(args,text=True).strip()


@contextmanager
def partition(image,offset,length,filesystem,target):
    if target.exists() or target.is_symlink():raise RuntimeError('Inspection mountpoint already exists: '+str(target))
    loop=run('losetup','--find','--show','--read-only','--offset',str(offset),'--sizelimit',str(length),str(image))
    mounted=False
    try:
        if run('blockdev','--getro',loop)!='1':raise RuntimeError('Loop device must be read-only')
        target.mkdir(mode=0o700)
        flags='ro,nodev,nosuid,noexec'+(',noload' if filesystem=='ext4' else '')
        subprocess.run(['mount','-t',filesystem,'-o',flags,loop,str(target)],check=True)
        mounted=True
        options=run('findmnt','-rn','-o','OPTIONS','--target',str(target)).split(',')
        if 'ro' not in options:raise RuntimeError('Read-only mount proof missing')
        yield target
    finally:
        # Never detach a loop still mounted, even if umount fails.
        if mounted:
            subprocess.run(['umount',str(target)],check=True)
        subprocess.run(['losetup','--detach',loop],check=True)
        if target.exists():target.rmdir()


def safe(root,relative):
    path=root/relative
    if not path.resolve().is_relative_to(root.resolve()):return None
    return path


def inventory(root,relative):
    path=safe(root,relative)
    if path is None:return {'path':relative,'external_symlink_skipped':True}
    if not path.exists():return {'path':relative,'exists':False}
    mode=path.stat().st_mode
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        return {'path':relative,'special_file_skipped':True}
    size=int(run('du','-sx','-B1','--',str(path)).split()[0])
    return {'path':relative,'exists':True,'allocated_bytes':size}


def read_small(root,relative):
    path=safe(root,relative)
    if path is None or not path.is_file() or path.stat().st_size>16384:return None
    return path.read_text(errors='replace')


def inspect():
    if os.geteuid()!=0:raise RuntimeError('Run as WSL root')
    if IMAGE.is_symlink() or not IMAGE.is_file():raise RuntimeError('Verified working image missing')
    manifest=json.loads((WORK/'working-copy.json').read_text())
    if manifest.get('state')!='VERIFIED_PRIVATE_WORKING_COPY_NOT_GOLDEN' or manifest.get('sanitized') or manifest.get('shrunk'):
        raise RuntimeError('Unexpected work state; no automatic retry over a modified image')
    if IMAGE.stat().st_size!=63864569856:raise RuntimeError('Working image size changed')
    before=IMAGE.stat()
    report={'state':'READ_ONLY_INSPECTION','image':str(IMAGE),'source_untouched':True}
    with ExitStack() as stack:
        root=stack.enter_context(partition(IMAGE,679936*512,124055519*512,'ext4',Path('/mnt/labrix-inspect-root')))
        config=stack.enter_context(partition(IMAGE,32768*512,32768*512,'vfat',Path('/mnt/labrix-inspect-config')))
        boot=stack.enter_context(partition(IMAGE,65536*512,614400*512,'vfat',Path('/mnt/labrix-inspect-boot')))
        release=read_small(root,'etc/os-release') or ''
        report['os']=[line for line in release.splitlines() if line.startswith(('ID=','VERSION_ID=','PRETTY_NAME='))]
        report['storage']=[inventory(root,p) for p in (
            'opt/sammoy','opt/containerd','var/lib/docker','var/lib/containerd','var/log',
            'home/admin','home/kiosk','root','etc/NetworkManager/system-connections')]
        units=safe(root,'etc/systemd/system')
        report['labrix_unit_files']=sorted(p.name for p in units.iterdir() if p.name.startswith(('sammoy2','labrix'))) if units and units.is_dir() else []
        report['enabled_units']={}
        if units and units.is_dir():
            for target in units.glob('*.wants'):
                if target.is_symlink() or not target.is_dir():continue
                report['enabled_units'][target.name]=sorted(p.name for p in target.iterdir() if p.name.startswith(('sammoy2','labrix','docker','ssh','sddm')))
        report['identity_files_present']={p:os.path.lexists(root/p) for p in (
            'etc/machine-id','var/lib/dbus/machine-id','etc/ssh/ssh_host_ed25519_key',
            'opt/sammoy/sammoy2/.env','opt/sammoy/login',
            'opt/sammoy/sammoy2/data/postgres','opt/sammoy/sammoy2/data/io-helper')}
        report['display_config']=read_small(root,'etc/sammoy2/display.conf')
        report['hardware_profile']=read_small(root,'opt/sammoy/sammoy2/.hardware-profile')
        report['config_partition_entries']=sorted(p.name for p in config.iterdir())
        report['boot_partition_entries']=sorted(p.name for p in boot.iterdir())
        report['fstab_mounts']=[]
        for line in (read_small(root,'etc/fstab') or '').splitlines():
            fields=line.split()
            if line.lstrip().startswith('#') or len(fields)<3:continue
            source=fields[0] if fields[0].startswith(('UUID=','PARTUUID=','LABEL=','/dev/')) else 'other-source'
            report['fstab_mounts'].append({'source':source,'mountpoint':fields[1],'filesystem':fields[2]})
    after=IMAGE.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise RuntimeError('Working file changed during read-only inspection')
    report['working_image_unchanged']=True
    (WORK/'inspection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    print('INSPECTION READY. All loops detached; image and source unchanged.',flush=True)

if __name__=='__main__':inspect()
