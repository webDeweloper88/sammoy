"""Owner-authenticated bridge to the legacy multi-post reporting services."""
from __future__ import annotations
import asyncio
import base64
import hmac
import ipaddress
import os
import re
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
import httpx
import qrcode
import yaml
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from app.telegram_bot.store import PairingStore

ENV_PATH=Path(os.getenv('RTU_WASH_REPORTS_ENV','/data/reports.env'))
POSTS_PATH=ENV_PATH.parent/'posts.yaml'
DATA_PATH=ENV_PATH.parent/'hub.sqlite3'
LOCK=asyncio.Lock()
def authorize(authorization: str = Header(default='')):
    expected=os.environ.get('TELEGRAM_SETUP_KEY','')
    if not expected or not hmac.compare_digest(authorization, 'Bearer '+expected):
        raise HTTPException(401,'Unauthorized')
app=FastAPI(docs_url=None,redoc_url=None,dependencies=[Depends(authorize)])
def read_env(): return dict(dotenv_values(ENV_PATH)) if ENV_PATH.exists() else {}
def atomic_write(path:Path,content:str):
    path.parent.mkdir(parents=True,exist_ok=True)
    with NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        f.write(content); temp=Path(f.name)
    temp.chmod(0o600);temp.replace(path)
def write_env(updates):
    values=read_env();values.update(updates)
    def quote(v): return "'"+str(v).replace('\\','\\\\').replace("'","\\'")+"'"
    atomic_write(ENV_PATH,'\n'.join(k+'='+quote(v) for k,v in values.items())+'\n')
def write_posts(site_id,name,posts):
    atomic_write(POSTS_PATH,yaml.safe_dump({'site':{'id':site_id,'name':name,'timezone':'Asia/Tashkent'},'posts':posts},allow_unicode=True,sort_keys=False))
def posts(): return (yaml.safe_load(POSTS_PATH.read_text()) or {}).get('posts',[]) if POSTS_PATH.exists() else []
def control(action,*names):
    p=subprocess.run(['supervisorctl','-c','/etc/supervisor.conf',action,*names],capture_output=True,text=True,timeout=25)
    if p.returncode: raise HTTPException(503,'Report service restart failed')
def active(name):
    p=subprocess.run(['supervisorctl','-c','/etc/supervisor.conf','status',name],capture_output=True,text=True,timeout=5)
    return 'RUNNING' in p.stdout
def public_status():
    env=read_env(); owner=PairingStore(DATA_PATH).owner()
    return {'ok':True,'available':True,'configured':bool(env.get('TELEGRAM_BOT_TOKEN')),'enabled':env.get('TELEGRAM_ENABLED')=='true' and env.get('TELEGRAM_LEADER','true')=='true' and active('bot'),'bot_username':env.get('TELEGRAM_BOT_USERNAME',''),'owner_paired':owner is not None,'leader':env.get('TELEGRAM_LEADER','true')=='true','primary_post':int(env.get('REPORT_PRIMARY_POST') or 1), 'owner_name':(owner['telegram_first_name'] or owner['telegram_username'] or '') if owner else '', 'configured_posts':len(posts()),'identity_configured':env.get('SITE_ID') not in ('','UNCONFIGURED',None),'posts':[{'id':p['id'],'name':p['name'],'host':p['host']} for p in posts()]}
@app.get('/status')
def status(): return public_status()
class Identity(BaseModel):
    site_id:str=Field(min_length=1,max_length=80)
    post_no:int=Field(ge=1,le=999)
    api_key:str=Field(min_length=32,max_length=128)
@app.post('/identity/sync')
async def identity(payload:Identity):
    async with LOCK:
        env=read_env();post_id=f'POST-{payload.post_no:02d}'
        if (env.get('SITE_ID'),env.get('POST_ID'),env.get('LOCAL_REPORT_API_KEY'))==(payload.site_id,post_id,payload.api_key):return {'ok':True}
        # Identity changes invalidate the previous site's destinations and pairing.
        PairingStore(DATA_PATH).reset_owner()
        write_env({'SITE_ID':payload.site_id,'SITE_NAME':payload.site_id,'POST_ID':post_id,'POST_NAME':f'Post {payload.post_no}','LOCAL_REPORT_API_KEY':payload.api_key,'SITE_REPORT_API_KEY':payload.api_key,'TELEGRAM_ENABLED':'false'})
        write_posts(payload.site_id,payload.site_id,[{'id':post_id,'name':f'Post {payload.post_no}','host':'127.0.0.1','port':8091,'api_key_env':'SITE_REPORT_API_KEY','enabled':True}])
        await asyncio.to_thread(control,'restart','report','hub','bot')
    return {'ok':True}
class Configure(BaseModel): token:str=Field(min_length=1,max_length=256)
@app.post('/configure-auto')
async def configure(payload:Configure):
    token=payload.token.strip()
    if not re.fullmatch(r'[0-9]{6,12}:[A-Za-z0-9_-]{30,100}',token):raise HTTPException(400,'Invalid bot token format')
    async with LOCK:
        env=read_env()
        if env.get('SITE_ID') in ('UNCONFIGURED','',None):raise HTTPException(409,'Сначала настройте мойку и номер поста через установку поста')
        if env.get('POST_ID')!=f"POST-{int(env.get('REPORT_PRIMARY_POST') or 1):02d}":raise HTTPException(409,'Telegram подключается на текущем главном посту')
        try:
            async with httpx.AsyncClient(timeout=10) as client:r=await client.get(f'https://api.telegram.org/bot{token}/getMe')
            result=r.json().get('result',{})
            if r.status_code!=200 or not result.get('username'):raise HTTPException(400,'Telegram rejected this token')
        except (httpx.HTTPError,ValueError):raise HTTPException(503,'Telegram is not reachable') from None
        if env.get('TELEGRAM_BOT_USERNAME')!=result['username']:PairingStore(DATA_PATH).reset_owner()
        write_env({'TELEGRAM_BOT_TOKEN':token,'TELEGRAM_BOT_USERNAME':result['username'],'TELEGRAM_ENABLED':'true'})
        await asyncio.to_thread(control,'restart','bot')
    return public_status()
@app.post('/disable')
async def disable():
    async with LOCK:
        write_env({'TELEGRAM_ENABLED':'false'});await asyncio.to_thread(control,'restart','bot')
    return public_status()
class Pairing(BaseModel):reset_owner:bool=False
@app.post('/pairing')
async def pairing(payload:Pairing):
    async with LOCK:
        env=read_env()
        if env.get('TELEGRAM_ENABLED')!='true':raise HTTPException(409,'Connect the bot first')
        store=PairingStore(DATA_PATH)
        if payload.reset_owner:store.reset_owner()
        elif store.owner():raise HTTPException(409,'Owner already paired')
        raw,expires=store.create_token(10,'owner-ui');link=f"https://t.me/{env['TELEGRAM_BOT_USERNAME']}?start={raw}"
        buffer=BytesIO();qrcode.make(link).save(buffer,format='PNG')
        return {'ok':True,'pairing_url':link,'expires_at':expires.isoformat(),'qr_data_url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}
@app.post('/discover')
async def discover(payload: dict = None):
    async with LOCK:
        env=read_env();site=env.get('SITE_ID');key=env.get('SITE_REPORT_API_KEY')
        if site in ('UNCONFIGURED','',None):raise HTTPException(409,'Сначала настройте мойку и номер поста через установку поста')
        if env.get('POST_ID')!=f"POST-{int(env.get('REPORT_PRIMARY_POST') or 1):02d}":raise HTTPException(409,'Поиск постов выполняется на посте 1')
        try:network=ipaddress.ip_network((payload or {}).get('cidr') or os.environ.get('REPORT_LAN_CIDR',''),strict=False)
        except ValueError:raise HTTPException(503,'LAN is not configured; rerun deploy/install-reports.py')
        if network.version!=4 or not network.is_private or network.is_loopback or network.num_addresses>256:raise HTTPException(409,'Automatic discovery supports IPv4 /24 or smaller LANs')
        semaphore=asyncio.Semaphore(32)
        async with httpx.AsyncClient(timeout=httpx.Timeout(1.5,connect=.7)) as client:
            async def probe(host):
                async with semaphore:
                    try:
                        r=await client.get(f'http://{host}:8091/api/v1/health',headers={'Authorization':'Bearer '+key});d=r.json()
                        if r.status_code!=200 or d.get('site_id')!=site or not re.fullmatch(r'POST-[0-9]{2,3}',str(d.get('post_id',''))):return None
                        return {'id':d['post_id'],'name':f"Post {int(d['post_id'].split('-')[1])}",'host':str(host),'port':8091,'api_key_env':'SITE_REPORT_API_KEY','enabled':True,'node':d.get('node_id',str(host))}
                    except (httpx.HTTPError,ValueError):return None
            found=await asyncio.gather(*(probe(str(host)) for host in network.hosts()))
            local=await probe('127.0.0.1')
        if not local:raise HTTPException(503,'Local report API unavailable')
        result={local['id']:local}
        for item in filter(None,found):
            previous=result.get(item['id'])
            if previous and previous['node']!=item['node']:raise HTTPException(409,'Duplicate post number: '+item['id'])
            if not previous:result[item['id']]=item
        # Preserve previously known offline stations, so a scan cannot hide missing income.
        for item in posts():result.setdefault(item['id'],dict(item))
        clean=sorted(result.values(),key=lambda p:p['id'])
        for p in clean:p.pop('node',None)
        write_posts(site,env.get('SITE_NAME',site),clean);await asyncio.to_thread(control,'restart','hub')
        return {'ok':True,'posts':[{'id':p['id'],'name':p['name'],'host':p['host']} for p in clean],'count':len(clean)}

@app.get('/aggregate/{period}')
async def aggregate(period: str, value: str):
    from datetime import date
    if period not in ('daily','weekly','monthly'):raise HTTPException(422,'Invalid period')
    try: selected=date.fromisoformat(value)
    except ValueError:raise HTTPException(422,'Invalid date')
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r=await client.get(f'http://127.0.0.1:8092/api/v1/aggregate/{period}',params={'value':selected.isoformat(),'refresh':'true'})
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError,ValueError):raise HTTPException(503,'Report hub is unavailable') from None


class Leadership(BaseModel):
    active:bool
    primary_post:int=Field(ge=1,le=100)

@app.post('/leadership')
async def leadership(payload:Leadership):
    async with LOCK:
        updates={'TELEGRAM_LEADER':'true' if payload.active else 'false','REPORT_PRIMARY_POST':str(payload.primary_post)}
        old=read_env()
        if any(old.get(k)!=v for k,v in updates.items()):
            write_env(updates);await asyncio.to_thread(control,'restart','bot')
    return {'ok':True,'leader':payload.active}

@app.get('/backup/export')
def export_backup():
    env=read_env();store=PairingStore(DATA_PATH)
    with store.connect() as conn:
        owner=conn.execute('SELECT * FROM telegram_owner WHERE id=1').fetchone()
        notifications=[dict(row) for row in conn.execute('SELECT key,value,updated_at FROM notification_state ORDER BY key')]
    keys=('TELEGRAM_BOT_TOKEN','TELEGRAM_BOT_USERNAME','TELEGRAM_ENABLED')
    return {'version':1,'site_id':env.get('SITE_ID'),'env':{k:env.get(k,'') for k in keys},
            'owner':dict(owner) if owner else None,'notification_state':notifications,'posts':posts()}

@app.post('/backup/import')
async def import_backup(payload:dict):
    async with LOCK:
        env=read_env()
        if payload.get('version')!=1 or payload.get('site_id')!=env.get('SITE_ID'):
            raise HTTPException(409,'Report backup belongs to another site/version')
        values=payload.get('env') or {}
        values={k:str(values.get(k,'')) for k in ('TELEGRAM_BOT_TOKEN','TELEGRAM_BOT_USERNAME','TELEGRAM_ENABLED')}
        store=PairingStore(DATA_PATH)
        owner=payload.get('owner')
        with store.connect() as conn:
            conn.execute('DELETE FROM telegram_owner')
            if owner:
                conn.execute('INSERT INTO telegram_owner(id,telegram_user_id,telegram_username,telegram_first_name,paired_at,revoked_at,is_active) VALUES(1,?,?,?,?,?,?)',
                    (owner['telegram_user_id'],owner.get('telegram_username'),owner.get('telegram_first_name'),owner['paired_at'],owner.get('revoked_at'),owner['is_active']))
            conn.execute('DELETE FROM notification_state')
            for row in payload.get('notification_state',[]):
                conn.execute('INSERT INTO notification_state(key,value,updated_at) VALUES(?,?,?)',(row['key'],row['value'],row['updated_at']))
        write_env(values)
        if payload.get('posts'):
            write_posts(env['SITE_ID'],env.get('SITE_NAME',env['SITE_ID']),payload['posts'])
        await asyncio.to_thread(control,'restart','hub','bot')
    return {'ok':True}

from app.operator_notifications import register as register_operator_calls
register_operator_calls(app,read_env,DATA_PATH,PairingStore)
