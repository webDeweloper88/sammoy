#!/usr/bin/env python3
"""Quiesced SAMMOY2 backup and restore rehearsal. Never restores over live DB."""
import argparse,contextlib,fcntl,hashlib,json,os,re,shlex,sqlite3,subprocess,tarfile,tempfile,urllib.request,uuid,shutil
from datetime import datetime,timezone
from pathlib import Path

class BusyPost(RuntimeError):pass

PROJECT=Path(__file__).resolve().parents[2]
WRITERS=('wash-engine','telegram-reports')
SUMMARY="""SELECT json_build_object(
'payments',(SELECT count(*) FROM payments),
'paid',(SELECT coalesce(sum(amount_sum),0) FROM payments),
'bonus',(SELECT coalesce(sum(bonus_sum),0) FROM payments),
'sessions',(SELECT count(*) FROM wash_sessions),
'cash_events',(SELECT count(*) FROM cash_events),
'card_balance',(SELECT coalesce(sum(balance_sum),0) FROM rfid_cards),
'card_bonus',(SELECT coalesce(sum(bonus_sum),0) FROM rfid_cards),
'recovery',(SELECT coalesce(sum(amount_sum),0) FROM recovery_credits WHERE status='unclaimed'),
'wallet_operations',(SELECT count(*) FROM shared_wallet_operations),
'wallet_cards',(SELECT count(*) FROM shared_wallet_cards),
'wallet_receipts',(SELECT count(*) FROM shared_wallet_funding_receipts),
'vip_uses',(SELECT coalesce(sum(used),0) FROM shared_wallet_vip_uses),
'nv9_cursors',(SELECT coalesce(json_object_agg(setting_key,setting_value),'{}') FROM app_settings WHERE setting_key LIKE 'nv9_cursor:%'))::text;"""

def docker(*args,**kw):
    return subprocess.run(shlex.split(os.environ.get('SAMMOY_DOCKER','docker'))+list(args),check=True,cwd=PROJECT,**kw)
def compose(*args,**kw):return docker('compose',*args,**kw)
def capture(*args):return compose(*args,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode().strip()
def pg(sql,dbname=None):
    # Database name is positional shell input, never executable shell text.
    return compose('exec','-T','postgres','sh','-c','exec psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "${1:-$POSTGRES_DB}" -c "$2"','sh',dbname or '',sql,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode().strip()
def copy_tree(service,source,destination):
    container=capture('ps','-a','-q',service)
    if not container:raise RuntimeError('Missing service: '+service)
    destination.mkdir(mode=0o700)
    with tempfile.TemporaryFile() as f:
        docker('cp',container+':'+source+'/.','-',stdout=f,stderr=subprocess.PIPE)
        f.seek(0)
        with tarfile.open(fileobj=f) as archive:archive.extractall(destination,members=safe_members(archive))

def snapshot_nv9(destination,running):
    destination.mkdir(mode=0o700)
    if not running:
        # A stopped helper has no SQLite writer; copy its complete stopped tree.
        destination.rmdir()
        copy_tree('io-helper','/var/lib/sammoy-io',destination)
        return
    remote='/tmp/sammoy-nv9-snapshot-'+uuid.uuid4().hex+'.sqlite3'
    code='import sqlite3,sys; s=sqlite3.connect("file:/var/lib/sammoy-io/nv9.sqlite3?mode=ro",uri=True); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()'
    container=capture('ps','-a','-q','io-helper')
    try:
        compose('exec','-T','io-helper','python','-c',code,remote,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        with tempfile.TemporaryFile() as f:
            docker('cp',container+':'+remote,'-',stdout=f,stderr=subprocess.PIPE);f.seek(0)
            with tarfile.open(fileobj=f) as archive:
                members=list(safe_members(archive));files=[m for m in members if m.isfile()]
                if len(files)!=1:raise RuntimeError('Unexpected NV9 snapshot archive')
                with archive.extractfile(files[0]) as src,(destination/'nv9.sqlite3').open('wb') as dst:shutil.copyfileobj(src,dst)
    finally:compose('exec','-T','io-helper','rm','-f',remote,stdout=subprocess.DEVNULL)

def source_commit():
    root=next((p for p in [PROJECT,*PROJECT.parents] if (p/'.git').exists()),PROJECT)
    result=subprocess.run(['git','-c','safe.directory='+str(root),'rev-parse','HEAD'],cwd=PROJECT,capture_output=True,text=True)
    return result.stdout.strip() if result.returncode==0 else None

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def journal(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite integrity check failed')
        row=c.execute('SELECT stream,total FROM counter WHERE id=1').fetchone()
        if not row:raise RuntimeError('NV9 counter missing')
        return {'stream':row[0],'total':row[1]}
def safe_members(archive):
    for m in archive.getmembers():
        p=Path(m.name)
        if p.is_absolute() or '..' in p.parts or not (m.isfile() or m.isdir()):raise RuntimeError('Unsafe archive member')
        yield m

@contextlib.contextmanager
def maintenance_lock():
    with (PROJECT/'.maintenance.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield

def backup(output):
    output=output.resolve()
    if output.exists():raise RuntimeError('Backup destination already exists')
    if PROJECT/'data'==output or PROJECT/'data' in output.parents:raise RuntimeError('Backups must be outside live data')
    output.parent.mkdir(parents=True,exist_ok=True)
    running=set(capture('ps','--status','running','--services').splitlines())
    if 'wash-engine' in running:
        with urllib.request.urlopen('http://127.0.0.1:8090/api/wash/state',timeout=4) as r:s=json.load(r)['state']
        if any(s.get(k) for k in ('creditSum','armedMode','activeMode','requestedOutput','walletTransferPending')):raise BusyPost('Post busy; backup postponed without changing money')
    stopped=[name for name in WRITERS if name in running]
    stage=output.with_name(output.name+'.partial')
    stage.mkdir(mode=0o700)
    try:
        if stopped:compose('stop',*stopped,stdout=subprocess.DEVNULL)
        (stage/'summary.json').write_text(json.dumps(json.loads(pg(SUMMARY)))+'\n')
        with (stage/'postgres.dump').open('wb') as f:
            compose('exec','-T','postgres','sh','-c','exec pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"',stdout=f,stderr=subprocess.PIPE)
        files=stage/'files';files.mkdir(mode=0o700)
        snapshot_nv9(files/'io-helper','io-helper' in running)
        copy_tree('telegram-reports','/data',files/'reports')
        nv9=journal(files/'io-helper/nv9.sqlite3')
        with tarfile.open(stage/'files.tar.gz','w:gz') as archive:
            for name in ('io-helper','reports'):archive.add(files/name,arcname='data/'+name)
            for name in ('.env','config','data/kiosk-assets','docker-compose.yml'):
                path=PROJECT/name
                if path.exists():archive.add(path,arcname=name)
        shutil.rmtree(files)
        manifest={'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'nv9':nv9,'quiesced':stopped,
                  'source_commit':source_commit(),
                  'files':{name:sha(stage/name) for name in ('postgres.dump','files.tar.gz','summary.json')}}
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for path in stage.iterdir():path.chmod(0o600)
        stage.rename(output)
        print('Backup complete:',output,flush=True)
    finally:
        if stage.exists():shutil.rmtree(stage)
        if stopped:
            # Preserve images and previous service state; do not start disabled services.
            order=[s for s in ('io-helper','wash-engine','telegram-reports') if s in stopped]
            compose('start',*order,stdout=subprocess.DEVNULL)

def verify(bundle):
    bundle=bundle.resolve();manifest=json.loads((bundle/'manifest.json').read_text())
    if manifest.get('format')!=1 or set(manifest.get('files',{}))!={'postgres.dump','files.tar.gz','summary.json'}:raise RuntimeError('Invalid manifest')
    for name,digest in manifest['files'].items():
        if sha(bundle/name)!=digest:raise RuntimeError('Backup checksum mismatch: '+name)
    with tempfile.TemporaryDirectory(prefix='sammoy-files-check-') as folder:
        with tarfile.open(bundle/'files.tar.gz') as archive:archive.extractall(folder,members=safe_members(archive))
        restored=journal(Path(folder)/'data/io-helper/nv9.sqlite3')
        if restored!=manifest['nv9']:raise RuntimeError('Restored NV9 differs')
        summary=json.loads((bundle/'summary.json').read_text())
        cursor=summary['nv9_cursors'].get('nv9_cursor:'+restored['stream'],{}).get('total',0)
        if cursor>restored['total']:raise RuntimeError('NV9 counter below database cursor')
    dbname='sammoy_restorecheck_'+uuid.uuid4().hex
    assert re.fullmatch('sammoy_restorecheck_[0-9a-f]{32}',dbname)
    pg('CREATE DATABASE "'+dbname+'";')
    try:
        remote='/tmp/'+dbname+'.dump'
        try:
            compose('cp',str(bundle/'postgres.dump'),'postgres:'+remote,stdout=subprocess.DEVNULL)
            compose('exec','-T','postgres','sh','-c','exec pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$1" "$2"','sh',dbname,remote,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        finally:compose('exec','-T','postgres','rm','-f',remote,stdout=subprocess.DEVNULL)
        if json.loads(pg(SUMMARY,dbname))!=summary:raise RuntimeError('Restored financial summary differs')
        (bundle/'verified.json').write_text(json.dumps({'verified_at':datetime.now(timezone.utc).isoformat(),'financial_summary_matches':True,'nv9_matches':True})+'\n')
        print('PASS restore rehearsal: disposable PostgreSQL, financial summary, restored files, NV9 integrity/cursor',flush=True)
    finally:pg('DROP DATABASE "'+dbname+'";')

def scheduled(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    needed=max(512*1024**2,int(pg('SELECT pg_database_size(current_database());'))*3)
    if shutil.disk_usage(root).free<needed:raise RuntimeError('Insufficient free space for safe backup')
    target=root/('sammoy-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup(target);verify(target)
    cutoff=datetime.now(timezone.utc).timestamp()-14*86400
    completed=sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r'sammoy-\d{8}T\d{6}Z',p.name) and (p/'verified.json').exists())
    for old in completed[:-3]:
        manifest=json.loads((old/'manifest.json').read_text())
        if datetime.fromisoformat(manifest['created_at']).timestamp()<cutoff and all(sha(old/name)==digest for name,digest in manifest['files'].items()):shutil.rmtree(old)

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['backup','verify','scheduled']);parser.add_argument('path',type=Path)
    args=parser.parse_args()
    with maintenance_lock():
        try:
            if args.action=='backup':backup(args.path)
            elif args.action=='verify':verify(args.path)
            else:scheduled(args.path)
        except BusyPost as exc:
            print(str(exc),flush=True);raise SystemExit(75)
if __name__=='__main__':main()
