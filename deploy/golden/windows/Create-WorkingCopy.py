#!/usr/bin/env python3
"""Create and verify a private Linux working image; never modifies source SD/image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


CHUNK = 64 * 1024
ZERO = bytes(CHUNK)
RESERVE = 24 * 1024**3

def digest(path, label, measure_sparse=False):
    total=path.stat().st_size;done=0;last=0
    h=hashlib.sha256();allocated=0
    print(label,flush=True)
    with path.open('rb') as stream:
        while True:
            block=stream.read(8*1024*1024)
            if not block:break
            h.update(block);done+=len(block)
            if measure_sparse:
                for offset in range(0,len(block),CHUNK):
                    piece=block[offset:offset+CHUNK]
                    if piece!=ZERO[:len(piece)]:allocated+=CHUNK
            if time.monotonic()-last>=5:
                print(f'  {done/1024**3:.2f} / {total/1024**3:.2f} GiB',flush=True)
                last=time.monotonic()
    return (h.hexdigest(),allocated) if measure_sparse else h.hexdigest()


def check_space(allocated, linux_free, backing_free):
    required=allocated+RESERVE
    print(f"Sparse copy upper bound: {allocated/1024**3:.2f} GiB; with build reserve: {required/1024**3:.2f} GiB",flush=True)
    if min(linux_free,backing_free)<required:
        raise RuntimeError("Insufficient space for measured sparse data plus 24 GiB build reserve; no copy created")
    return required


def read_expected(source):
    line=Path(str(source)+'.sha256').read_text(encoding='utf-8-sig').strip()
    parts=line.split(None,1)
    value=parts[0].lower() if parts else ''
    if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid SHA-256 sidecar')
    if len(parts)!=2 or parts[1].lstrip('*')!=source.name:
        raise ValueError('SHA-256 sidecar belongs to another filename')
    return value


def validate_layout(layout, size):
    table=layout.get('partitiontable',{})
    if table.get('label')!='gpt' or table.get('sectorsize')!=512:
        raise ValueError('Expected inspected GPT/512-byte source layout')
    parts=table.get('partitions',[])
    if [(p.get('start'),p.get('size')) for p in parts]!=[(32768,32768),(65536,614400),(679936,124055519)]:
        raise ValueError('Partition layout differs from inspected source')
    if (parts[-1]['start']+parts[-1]['size'])*512>size:
        raise ValueError('Partition exceeds image size')


def verified_copy(source, partial, expected):
    if partial.exists() or partial.is_symlink():raise ValueError('Partial exists; refusing overwrite')
    # Same chunk size as preflight: allocation is bounded by the measured data.
    fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as target,source.open('rb') as stream:
        while True:
            piece=stream.read(CHUNK)
            if not piece:break
            if piece==ZERO[:len(piece)]:target.seek(len(piece),os.SEEK_CUR)
            else:target.write(piece)
        target.truncate(source.stat().st_size)
        target.flush();os.fsync(target.fileno())
    partial.chmod(0o600)
    if partial.stat().st_size!=source.stat().st_size:raise RuntimeError('Working size mismatch; partial retained')
    if digest(partial,'Verifying WORKING copy...')!=expected:
        raise RuntimeError('Working hash mismatch; partial retained, original unchanged')


def create(source, workdir, backing_free):
    source=Path(source)
    workdir=Path(workdir)
    if source.is_symlink() or not source.is_file():raise ValueError('Source must be a plain image file')
    source=source.resolve()
    if source.stat().st_size!=63864569856:raise ValueError('Source image size mismatch')
    if workdir!=Path('/var/lib/labrix-golden-build') or workdir.is_symlink() or workdir.exists():
        raise ValueError('Working directory must be new /var/lib/labrix-golden-build; refusing overwrite')
    for tool in ('sfdisk','stat'):
        if not shutil.which(tool):raise RuntimeError('Missing Linux tool: '+tool)
    filesystem=subprocess.check_output(['stat','-f','-c','%T',str(workdir.parent)],text=True).strip()
    if filesystem not in ('ext2/ext3','ext4','btrfs','xfs'):
        raise RuntimeError('Working copy must be on the Linux filesystem, not a Windows mount')
    expected=read_expected(source)
    checksum,allocated=digest(source,'Verifying ORIGINAL image and measuring sparse data (read-only)...',measure_sparse=True)
    if checksum!=expected:
        raise RuntimeError('Original hash mismatch; no copy created')
    check_space(allocated,shutil.disk_usage(workdir.parent).free,backing_free)
    layout=json.loads(subprocess.check_output(['sfdisk','--json',str(source)],text=True))
    validate_layout(layout,source.stat().st_size)
    original_stat=source.stat()
    os.umask(0o077)
    workdir.mkdir(mode=0o700)
    partial=workdir/'LABRIX-WORK.img.partial'
    image=workdir/'LABRIX-WORK.img'
    # Sparse copy skips zero ranges, but its logical size/hash remain identical.
    # No reflink: later edits cannot depend on the Windows source filesystem.
    print('Creating independent sparse working copy. This can take several minutes...',flush=True)
    verified_copy(source,partial,expected)
    after=source.stat()
    if after.st_size!=original_stat.st_size or after.st_mtime_ns!=original_stat.st_mtime_ns:
        raise RuntimeError('Source changed during copy; partial retained')
    partial.rename(image)
    report={'format':1,'state':'VERIFIED_PRIVATE_WORKING_COPY_NOT_GOLDEN',
            'source':str(source),'source_sha256':expected,'working_image':str(image),
            'logical_bytes':image.stat().st_size,'allocated_bytes':image.stat().st_blocks*512,
            'source_unchanged':True,'sanitized':False,'shrunk':False}
    (workdir/'working-copy.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    print('COPY READY. No mounts, cleaning, partition resizing or SD writes performed.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--workdir',default='/var/lib/labrix-golden-build')
    parser.add_argument('--backing-free-bytes',type=int,required=True)
    args=parser.parse_args()
    create(args.source,args.workdir,args.backing_free_bytes)
