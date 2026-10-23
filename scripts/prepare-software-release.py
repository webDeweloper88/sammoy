#!/usr/bin/env python3
"""Interactive release preparation. Does not publish or restart stations."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
SERVICES={'wash-engine':'services/wash-engine','io-helper':'services/io-helper',
          'kiosk-ui':'apps/kiosk-ui','telegram-reports':'services/telegram-reports'}
VERSION=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def capture(args,**kwargs):
    return subprocess.check_output([str(a) for a in args],text=True,**kwargs).strip()


def metadata(number,version,notes):
    if not 1<=number<=2**53-1:raise ValueError('Release number must be a positive integer')
    if not VERSION.fullmatch(version):raise ValueError('Invalid version (max 64 letters, digits, dots, dashes or underscores)')
    if not isinstance(notes,dict) or set(notes)!={'ru','uz','en'} or any(not isinstance(v,str) or not 1<=len(v.strip())<=4000 for v in notes.values()):
        raise ValueError('Provide nonempty release notes in ru, uz and en (max 4000 characters each)')
    return {k:v.strip() for k,v in notes.items()}


def source_info(root):
    if capture(['git','-C',root,'status','--porcelain']):
        raise ValueError('Commit or remove pending source changes first. Releases are built from a clean Git commit.')
    return capture(['git','-C',root,'rev-parse','HEAD'])


def export_source(root,destination):
    # Build only the committed tree; local .env, databases and SSH files cannot enter contexts.
    archive=destination/'source.tar'
    subprocess.run(['git','-C',str(root),'archive','--format=tar','--output',str(archive),'HEAD'],check=True)
    source=destination/'source';source.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target=(source/member.name).resolve()
            if source not in target.parents or not (member.isfile() or member.isdir()):
                raise ValueError('Unsupported path or link in committed source')
        tar.extractall(source)
    archive.unlink()
    return source


def prepare(args,root=ROOT):
    notes=metadata(args.number,args.version,args.notes)
    commit=source_info(root)
    key=args.private.expanduser().resolve();output=args.output.expanduser().resolve()
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError('Signing key must exist and have permissions 0600 (or stricter)')
    if key.is_relative_to(root):raise ValueError('Keep the private signing key outside the Git repository')
    if output.exists():raise ValueError('Output already exists; use a new release directory')
    if output.is_relative_to(root):raise ValueError('Keep generated releases outside the Git repository')
    docker=shlex.split(args.docker_command)
    if not docker:raise ValueError('Docker command is empty')
    plan={'release_no':args.number,'version':args.version,'commit':commit,'services':list(SERVICES),
          'output':str(output),'notes':notes,'publishes':False,'changes_running_stations':False}
    print(json.dumps(plan,ensure_ascii=False,indent=2),flush=True)
    if args.plan:return
    # Fail before expensive builds if the Docker daemon or signing runtime is unavailable.
    capture(docker+['info','--format','{{.Architecture}}'])
    signer=json.loads(capture(docker+['image','inspect',args.signer_image]))[0]['Id']
    subprocess.run(docker+['run','--rm','--network','none','-v',str(key)+':/keys/signing.pem:ro','--entrypoint','python',signer,'-c',"from pathlib import Path;from cryptography.hazmat.primitives.serialization import load_pem_private_key;from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey;assert isinstance(load_pem_private_key(Path('/keys/signing.pem').read_bytes(),None),Ed25519PrivateKey)"],check=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='labrix-release-',dir=output.parent) as temp:
        workspace=Path(temp);source=export_source(root,workspace);images={}
        tag='release-'+args.version.lower()+'-'+uuid4().hex[:10]
        for service,context in SERVICES.items():
            image='sammoy2-'+service+':'+tag
            subprocess.run(docker+['build','--platform','linux/arm64','--label','org.opencontainers.image.revision='+commit,
                                  '-t',image,str(source/context)],check=True)
            images[service]=image
        (workspace/'images.json').write_text(json.dumps(images))
        (workspace/'notes.json').write_text(json.dumps(notes,ensure_ascii=False))
        # Signing runs in an existing trusted Python/cryptography image; host Python needs no extra packages.
        # Only this key is mounted, not the directory containing other credentials.
        command=docker+['run','--rm','--network','none',
            '-v','/var/run/docker.sock:/var/run/docker.sock','-v',str(args.docker_binary)+':/usr/bin/docker:ro',
            '-v',str(source)+':/work:ro','-v',str(key)+':/keys/signing.pem:ro',
            '-v',str(workspace)+':/release','--entrypoint','python',signer,
            '/work/scripts/build-software-release.py','build','--private','/keys/signing.pem',
            '--output','/release/result','--number',str(args.number),'--version',args.version,
            '--images','/release/images.json','--notes','/release/notes.json']
        # Root signer returns ownership only of generated public artifacts.
        ownership="import pathlib,os;p=pathlib.Path('/release/result');\nif p.exists():\n os.chown(p,"+str(os.getuid())+","+str(os.getgid())+");p.chmod(0o755)\n for f in p.rglob('*'):\n  os.chown(f,"+str(os.getuid())+","+str(os.getgid())+");f.chmod(0o755 if f.is_dir() else 0o644)"
        try:
            subprocess.run(command,check=True)
        finally:
            subprocess.run(docker+['run','--rm','--network','none','-v',str(workspace)+':/release','--entrypoint','python',signer,'-c',ownership],check=True)
        result=workspace/'result'
        (result/'build.json').write_text(json.dumps({**plan,'images':images},ensure_ascii=False,indent=2)+'\n')
        # Promote only a completed build on the same filesystem.
        if output.exists():raise ValueError('Output appeared during the build; refusing replacement')
        result.rename(output)
    print('\nREADY: '+str(output/'release.json'))
    print('Upload the archive and import release.json in Pay → Software updates. Not published automatically.')


def main():
    parser=argparse.ArgumentParser(description='Prepare a signed LABRIX application release from committed source')
    parser.add_argument('--number',type=int);parser.add_argument('--version');parser.add_argument('--notes',type=Path)
    parser.add_argument('--private',type=Path,default=ROOT.parent/'ssh/labrix_updates_signing.pem')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--docker-command',default='docker',help='Docker CLI or local privileged wrapper command')
    parser.add_argument('--docker-binary',type=Path,default=Path('/usr/bin/docker'))
    parser.add_argument('--signer-image',default='sammoy2-wash-engine:latest',help='Existing trusted Python image with cryptography')
    parser.add_argument('--plan',action='store_true',help='Validate inputs and show the plan without Docker builds or signing')
    args=parser.parse_args()
    try:
        if args.number is None:args.number=int(input('Следующий номер выпуска (например 3): ').strip())
        if not args.version:args.version=input('Версия ['+datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%Y.%m.%d')+'.1]: ').strip() or datetime.now(ZoneInfo('Asia/Tashkent')).strftime('%Y.%m.%d')+'.1'
        args.notes=json.loads(args.notes.read_text()) if args.notes else {lang:input('Описание изменений ('+lang+'): ') for lang in ('ru','uz','en')}
        if args.output is None:args.output=ROOT.parent/'artifacts/software-releases'/args.version
        prepare(args)
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print('RELEASE NOT READY: '+str(error),file=sys.stderr);return 1
    except (KeyboardInterrupt,EOFError):
        print('\nCancelled; release was not published.',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
