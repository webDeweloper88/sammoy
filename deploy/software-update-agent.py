#!/usr/bin/python3
"""Root-owned, fixed-function installer for signed application images only."""
import fcntl
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import shutil
import socket
from socketserver import ThreadingMixIn, UnixStreamServer
import sqlite3
import sys
import struct
import subprocess
import tarfile
import threading
import time
import urllib.request
from uuid import UUID
from update_archive import config_references
from update_protocol import verify_release, canonical, SERVICES, DATABASE_CONTRACT_PROGRAM

ROOT=Path('/opt/sammoy/sammoy2')
STORE=Path('/var/lib/labrix-updates')
SOCKET=Path('/run/sammoy2-admin/updates.sock')
PUBLIC=Path('/etc/labrix-updates/signing.pub.pem')
HARDWARE=Path('/etc/labrix-updates/hardware')
GIB=1024**3
RETAIN=48*3600
lock=threading.RLock()

class UpdateError(RuntimeError):pass

def run(*args,timeout=240):
    p=subprocess.run(args,cwd=ROOT,capture_output=True,timeout=timeout)
    if p.returncode:raise UpdateError('command_failed:'+args[0])
    return p.stdout

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    p=path.with_suffix('.tmp')
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
    os.replace(p,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def load(path,default=None):return json.loads(path.read_text()) if path.exists() else default

def get(port,path):
    try:return json.load(urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=5))
    except Exception:raise UpdateError('station_unavailable') from None

def idle():
    s=get(8090,'/api/wash/state')['state']
    if any(s.get(k) for k in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld','vipRemainingSeconds')):
        raise UpdateError('station_busy')
    if s.get('outputsOffConfirmed') is not True:raise UpdateError('outputs_not_confirmed_off')
    f=get(8080,'/bill/filter')
    if f.get('active') or f.get('fault'):raise UpdateError('cash_input_not_ready')
    return {'pulses':f['published_pulses'],'stream':get(8080,'/io').get('nv9_stream_id')}

def maintenance(job_id,action):
    token=(PUBLIC.parent/'agent.token').read_text().strip()
    req=urllib.request.Request('http://127.0.0.1:8090/api/internal/software/'+action,data=json.dumps({'id':job_id}).encode(),headers={'Content-Type':'application/json','X-Update-Agent-Token':token},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            if not json.load(r).get('ok'):raise UpdateError('maintenance_interlock_failed')
    except Exception:raise UpdateError('maintenance_interlock_failed') from None


def compose():
    info=json.loads(run('docker','inspect','sammoy2-wash-engine'))[0]
    files=info['Config']['Labels']['com.docker.compose.project.config_files'].split(',')
    allowed={'docker-compose.yml','docker-compose.nfc-relay.yml','docker-compose.dry-fog.yml','docker-compose.relay-only.yml'}
    if not files or any(Path(f).parent!=ROOT or Path(f).name not in allowed for f in files):raise UpdateError('unsupported_compose_profile')
    return ['docker','compose','-p','sammoy2']+[x for f in files for x in ('-f',f)]

def schema_contract(image):
    return run('docker','run','--rm','--network','none','--entrypoint','python',image,'-c',DATABASE_CONTRACT_PROGRAM).decode().strip()

def verify(envelope):
    try:m=verify_release(envelope,PUBLIC.read_bytes())
    except (ValueError,OSError):raise UpdateError('invalid_release_signature') from None
    if not HARDWARE.is_file() or HARDWARE.read_text().strip()!=m['hardware'] or os.uname().machine!=m['arch']:
        raise UpdateError('incompatible_hardware')
    installed=load(STORE/'installed.json',{})
    if m['release_no']<=installed.get('release_no',0):raise UpdateError('release_not_newer')
    return m

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise UpdateError('artifact_redirect_forbidden')

def space_required(m,db_bytes):
    a=m['artifact']
    return a['bytes']+a['unpacked_bytes']+a['image_bytes']+2*db_bytes+GIB

def download(m,folder):
    a=m['artifact'];dest=folder/'package.tar.gz';partial=folder/'package.partial'
    h=hashlib.sha256();count=0
    try:
        with urllib.request.build_opener(NoRedirect).open(a['url'],timeout=30) as r,partial.open('wb') as f:
            if r.status!=200:raise UpdateError('download_failed')
            while True:
                block=r.read(1024*1024)
                if not block:break
                count+=len(block)
                if count>a['bytes']:raise UpdateError('artifact_size_mismatch')
                h.update(block);f.write(block)
            f.flush();os.fsync(f.fileno())
        if count!=a['bytes'] or h.hexdigest()!=a['sha256']:raise UpdateError('artifact_checksum_mismatch')
        os.replace(partial,dest)
    finally:partial.unlink(missing_ok=True)
    return dest

def unpack(archive,folder,m):
    # Never extract names, links, permissions, devices or host scripts from a tar.
    target=folder/'images.tar';limit=m['artifact']['unpacked_bytes']
    with tarfile.open(archive,'r|gz') as t:
        members=iter(t)
        first=next(members,None)
        if first is None or first.name!='images.tar' or not first.isfile() or first.size!=limit:
            raise UpdateError('invalid_package_layout')
        source=t.extractfile(first)
        with target.open('wb') as out:
            shutil.copyfileobj(source,out,1024*1024);out.flush();os.fsync(out.fileno())
        if next(members,None) is not None:raise UpdateError('invalid_package_layout')
    if target.stat().st_size!=limit:raise UpdateError('artifact_size_mismatch')
    # A docker save by image ID carries no mutable repository tags. Reject
    # archives that could replace live :latest tags during the download phase.
    try:config_references(target,set(m['services'].values()))
    except ValueError as exc:raise UpdateError(str(exc)) from None
    return target

def db_info():
    d=json.loads(run('docker','inspect','sammoy2-postgres'))[0]
    env=dict(v.split('=',1) for v in d['Config']['Env'] if '=' in v)
    user=env.get('POSTGRES_USER','');database=env.get('POSTGRES_DB','')
    if any(not x or not x.replace('_','').isalnum() for x in (user,database)):raise UpdateError('invalid_database_identity')
    size=int(run('docker','exec','sammoy2-postgres','psql','-U',user,'-d',database,'-Atc','SELECT pg_database_size(current_database())').strip())
    return user,database,size

def backup(folder,user,database):
    path=folder/'database.dump'
    with path.open('wb') as f:
        p=subprocess.run(['docker','exec','sammoy2-postgres','pg_dump','-U',user,'-d',database,'-Fc'],stdout=f,stderr=subprocess.DEVNULL,timeout=240)
        if p.returncode:raise UpdateError('database_backup_failed')
        f.flush();os.fsync(f.fileno())
    os.chmod(path,0o600)
    with path.open('rb') as f:
        p=subprocess.run(['docker','exec','-i','sammoy2-postgres','pg_restore','--list'],stdin=f,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        if p.returncode:raise UpdateError('database_backup_invalid')
    config=folder/'configuration';config.mkdir(mode=0o700)
    for name in ('.env','.hardware-profile','docker-compose.yml','docker-compose.nfc-relay.yml','docker-compose.dry-fog.yml','docker-compose.relay-only.yml'):
        p=ROOT/name
        if p.is_file():shutil.copy2(p,config/name);os.chmod(config/name,0o600)

def journal():
    p=ROOT/'data/io-helper/nv9.sqlite3'
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as c:
        row=c.execute('SELECT stream,total FROM counter WHERE id=1').fetchone()
    return {'stream':row[0],'pulses':row[1]}

def health(expected,baseline):
    for _ in range(40):
        try:
            if get(8090,'/api/wash/state')['state'].get('outputsOffConfirmed') is not True:raise UpdateError('outputs_not_confirmed_off')
            current=journal()
            if current['stream']!=baseline['stream'] or current['pulses']<baseline['pulses']:raise UpdateError('cash_journal_changed')
            for svc,image in expected.items():
                d=json.loads(run('docker','inspect','sammoy2-'+svc))[0]
                if d['Image']!=image or not d['State']['Running'] or d['State'].get('Health',{}).get('Status','healthy')!='healthy':raise UpdateError('service_unhealthy')
            return
        except (UpdateError,KeyError):time.sleep(1)
    raise UpdateError('health_check_failed')

def cleanup(now=None):
    now=now or time.time()
    for folder in STORE.glob('jobs/*'):
        receipt=load(folder/'job.json',{})
        if receipt.get('status') not in ('completed','failed','rolled_back') or now-receipt.get('finished_at',now)<RETAIN:continue
        for tag in receipt.get('rollback_tags',{}).values():
            try:run('docker','image','rm',tag)
            except UpdateError:pass
        for name in ('database.dump','configuration','package.tar.gz','images.tar'):
            p=folder/name
            if p.is_dir():shutil.rmtree(p)
            else:p.unlink(missing_ok=True)
        if not receipt.get('cleaned_at'):receipt['cleaned_at']=now;atomic(folder/'job.json',receipt)


def perform(job):
    folder=STORE/'jobs'/job['id'];stopped=False;started=False
    previous={};tags={}
    def save(status,**extra):
        job.update(status=status,**extra);atomic(folder/'job.json',job)
    try:
        m=verify(job['envelope']);cmd=compose()
        cleanup()
        user,database,db_bytes=db_info()
        if shutil.disk_usage(STORE).free<space_required(m,db_bytes):raise UpdateError('insufficient_space')
        save('downloading');archive=download(m,folder);images=unpack(archive,folder,m)
        for svc in m['services']:
            info=json.loads(run('docker','inspect','sammoy2-'+svc))[0]
            if info['Config']['Image']!='sammoy2-'+svc+':latest':raise UpdateError('unsupported_image_tag')
            previous[svc]=info['Image']
        engine=json.loads(run('docker','inspect','sammoy2-wash-engine'))[0]['Image']
        if schema_contract(engine)!=m['db_contract']:raise UpdateError('database_contract_changed')
        references=config_references(images,set(m['services'].values()))
        run('docker','load','-i',str(images))
        targets={}
        for svc,image in m['services'].items():
            try:info=json.loads(run('docker','image','inspect',image))[0]
            except UpdateError:info=json.loads(run('docker','image','inspect',references[image]))[0]
            targets[svc]=info['Id']
            if info['Architecture']!='arm64' or info['Os']!='linux':raise UpdateError('incompatible_image')
            if svc=='wash-engine' and schema_contract(targets[svc])!=m['db_contract']:raise UpdateError('database_contract_changed')
            tags[svc]='sammoy2-update-rollback:'+svc+'-'+UUID(job['id']).hex
            run('docker','tag',previous[svc],tags[svc])
        images.unlink();archive.unlink()
        # Recheck immediately before stopping, not only before a long download.
        maintenance(job['id'],'prepare')
        baseline=idle();save('installing',previous_images=previous,rollback_tags=tags,baseline=baseline)
        run(*cmd,'stop','-t','30','wash-engine','telegram-reports');stopped=True
        run(*cmd,'stop','-t','15','io-helper')
        if journal()!=baseline:raise UpdateError('cash_changed_before_install')
        backup(folder,user,database)
        for svc,image in targets.items():run('docker','tag',image,'sammoy2-'+svc+':latest')
        started=True
        run(*cmd,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120',*sorted(SERVICES))
        health(targets,baseline)
        atomic(STORE/'installed.json',{'release_no':m['release_no'],'version':m['version'],'installed_at':time.time(),'job_id':job['id']})
        save('completed',finished_at=time.time())
    except Exception as exc:
        error=str(exc) if isinstance(exc,UpdateError) else 'installer_failed'
        if stopped:
            try:
                # Never restart a newly active customer session to roll back.
                if started:idle()
                for svc,image in previous.items():run('docker','tag',image,'sammoy2-'+svc+':latest')
                run(*cmd,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120',*sorted(SERVICES))
                health(previous,job['baseline']);save('rolled_back',error=error,finished_at=time.time())
            except Exception:save('needs_review',error=error)
        else:save('failed',error=error,finished_at=time.time())
    finally:
        try:maintenance(job['id'],'release')
        except Exception:pass
        for name in ('package.partial','package.tar.gz','images.tar'):(folder/name).unlink(missing_ok=True)


def worker(job):
    time.sleep(2) # Return the durable acknowledgement before the backend stops.
    perform(job)


def submit(value):
    if not isinstance(value,dict) or set(value)!={'id','envelope'}:raise UpdateError('invalid_request')
    key=str(UUID(value['id']));folder=STORE/'jobs'/key
    existing=load(folder/'job.json',{})
    if existing:
        if canonical(existing['envelope'])!=canonical(value['envelope']):raise UpdateError('job_id_conflict')
        return public_job(existing)
    verify(value['envelope'])
    for f in STORE.glob('jobs/*/job.json'):
        if load(f,{}).get('status') not in ('completed','failed','rolled_back'):
            raise UpdateError('another_update_pending')
    idle()
    job={'id':key,'envelope':value['envelope'],'status':'queued','created_at':time.time()}
    atomic(folder/'job.json',job)
    threading.Thread(target=worker,args=(job,),daemon=True).start()
    return public_job(job)

def public_job(job):
    return {k:job.get(k) for k in ('id','status','error','created_at','finished_at')}

def status():
    jobs=sorted(STORE.glob('jobs/*/job.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    return {'ok':True,'agent_protocol':1,'installed':load(STORE/'installed.json',{'release_no':0,'version':'legacy'}),
            'free_bytes':shutil.disk_usage(STORE).free,'last_job':public_job(load(jobs[0])) if jobs else None,
            'trusted_key_configured':PUBLIC.is_file(),'hardware':HARDWARE.read_text().strip() if HARDWARE.is_file() else None}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def handle_request(self):
        code=200;result={}
        try:
            _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=0:raise UpdateError('forbidden')
            with lock:
                if self.command=='GET' and self.path=='/status':result=status()
                elif self.command=='GET' and self.path.startswith('/jobs/'):
                    job=load(STORE/'jobs'/str(UUID(self.path.split('/')[-1]))/'job.json')
                    if not job:raise UpdateError('job_not_found')
                    result=public_job(job)
                elif self.command=='POST' and self.path=='/jobs':
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=65536:raise UpdateError('invalid_request')
                    result=submit(json.loads(self.rfile.read(size)));code=202
                else:raise UpdateError('not_found')
        except (ValueError,UpdateError,OSError) as exc:code=409;result={'detail':str(exc) if isinstance(exc,UpdateError) else 'invalid_request'}
        encoded=json.dumps(result).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
    do_GET=handle_request
    do_POST=handle_request

class Server(ThreadingMixIn,UnixStreamServer):daemon_threads=True

def main():
    STORE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if sys.argv[1:]==['--cleanup']:
        cleanup();return
    # One root process owns the installer even if systemd is restarted.
    guard=(STORE/'agent.lock').open('w');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for p in STORE.glob('jobs/*/job.json'):
        job=load(p,{})
        if job.get('status') not in ('completed','failed','rolled_back','needs_review'):
            job.update(status='needs_review',error='installer_interrupted');atomic(p,job)
    cleanup();SOCKET.parent.mkdir(parents=True,exist_ok=True,mode=0o700);SOCKET.unlink(missing_ok=True)
    with Server(str(SOCKET),Handler) as server:
        os.chmod(SOCKET,0o600);server.serve_forever()

if __name__=='__main__':main()
