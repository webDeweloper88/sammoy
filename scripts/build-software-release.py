#!/usr/bin/env python3
"""Offline build/sign tool. Private signing material stays on the release machine."""
import argparse
import base64
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from update_archive import config_references
from update_protocol import canonical,validate_manifest,SERVICES,DATABASE_CONTRACT_PROGRAM
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def run(*args):return subprocess.check_output(args)

def main():
 p=argparse.ArgumentParser();subs=p.add_subparsers(dest='command',required=True)
 g=subs.add_parser('keygen');g.add_argument('--private',type=Path,required=True);g.add_argument('--public',type=Path,required=True)
 b=subs.add_parser('build');b.add_argument('--private',type=Path,required=True);b.add_argument('--output',type=Path,required=True);b.add_argument('--number',type=int,required=True);b.add_argument('--version',required=True);b.add_argument('--notes',type=Path,required=True);b.add_argument('--images',type=Path,required=True)
 a=p.parse_args()
 if a.command=='keygen':
  if a.private.exists() or a.public.exists():raise RuntimeError('Refusing to overwrite signing keys')
  key=Ed25519PrivateKey.generate();a.private.parent.mkdir(parents=True,exist_ok=True)
  fd=os.open(a.private,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as f:f.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
  a.public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
  print('Created signing key. Back up the private file securely; upload only the public key.')
  return
 if a.output.exists():raise RuntimeError('Release output must be a new directory')
 key=serialization.load_pem_private_key(a.private.read_bytes(),password=None)
 if not isinstance(key,Ed25519PrivateKey):raise RuntimeError('Ed25519 private key required')
 specs=json.loads(a.images.read_text())
 if not specs or not set(specs)<=SERVICES or 'wash-engine' not in specs:raise RuntimeError('Invalid application services')
 images={};total=0
 for svc,ref in specs.items():
  info=json.loads(run('docker','image','inspect',ref))[0]
  if info['Architecture']!='arm64' or info['Os']!='linux':raise RuntimeError('Only ARM64 Linux releases are supported')
  images[svc]=info['Id'];total+=info['Size']
 contract=run('docker','run','--rm','--network','none','--entrypoint','python',images['wash-engine'],'-c',DATABASE_CONTRACT_PROGRAM).decode().strip()
 a.output.mkdir(parents=True,mode=0o700)
 # Save by immutable ID: no :latest tags may be loaded before installation.
 with tempfile.TemporaryDirectory(dir=a.output) as d:
  image_tar=Path(d)/'images.tar';subprocess.run(['docker','save','-o',str(image_tar),*sorted(set(images.values()))],check=True)
  references=config_references(image_tar)
  images={svc:next(config for config,native in references.items() if native==image or config==image) for svc,image in images.items()}
  archive=a.output/'package.tar.gz'
  with tarfile.open(archive,'w:gz',compresslevel=3) as t:t.add(image_tar,arcname='images.tar',recursive=False)
  unpacked=image_tar.stat().st_size
 sha=hashlib.sha256()
 with archive.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):sha.update(block)
 digest=sha.hexdigest();now=datetime.now(timezone.utc)
 m={'schema':1,'product':'labrix-wash','release_no':a.number,'version':a.version,'hardware':'cubie-a7a','arch':'aarch64','channel':'stable','issued_at':now.isoformat(),'expires_at':(now+timedelta(days=90)).isoformat(),'notes':json.loads(a.notes.read_text()),'artifact':{'url':'https://pay.labrix.uz/api/v1/software/artifacts/'+digest,'sha256':digest,'bytes':archive.stat().st_size,'unpacked_bytes':unpacked,'image_bytes':total},'services':images,'db_contract':contract,'agent_protocol':1,'wallet_protocol':1,'runtime_contract':1}
 validate_manifest(m)
 envelope={'manifest':m,'signature':base64.b64encode(key.sign(canonical(m))).decode()}
 archive.rename(a.output/(digest+'.tar.gz'));(a.output/'release.json').write_text(json.dumps(envelope,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'release_no':a.number,'version':a.version,'sha256':digest,'bytes':m['artifact']['bytes']}))

if __name__=='__main__':main()
