"""Owner-controlled durable site queue; root installer has a separate trust gate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import threading
import time
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID,uuid4
import httpx
from fastapi import APIRouter,Depends,HTTPException,Header
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb
from .auth import require_role
from .db import db
from .security import verify_password
from .update_protocol import verify_release

router=APIRouter(prefix='/api/owner/updates')
agent_router=APIRouter(prefix='/api/internal/software')
Owner=Annotated[dict,Depends(require_role('owner'))]
QUEUE_KEY='software_update_queue_v1'
mutex=threading.RLock()
started=False
TERMINAL={'completed','cancelled','failed','needs_review'}


def agent(method='GET',path='/status',value=None):
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds='/run/sammoy2-admin/updates.sock'),timeout=5) as c:
            r=c.request(method,'http://localhost'+path,json=value)
        if r.status_code>=400:raise HTTPException(409,r.json().get('detail','installer_unavailable'))
        return r.json()
    except (httpx.HTTPError,ValueError):raise HTTPException(503,'installer_unavailable') from None


def local_status():
    from .wash_logic import wash_runtime
    from .admin_service import require_idle
    try:require_idle(wash_runtime);ready=wash_runtime.snapshot()['state'].get('outputsOffConfirmed') is True
    except HTTPException:ready=False
    try:info=agent()
    except HTTPException:info={'ok':False,'error':'installer_not_installed','installed':{'release_no':0,'version':'legacy'}}
    return {**info,'ready':ready,'protocol':1}


def cfg():
    from .wallet_api import configuration
    return configuration()


def manage_allowed(c):return not c['enabled'] or c['local_post']==c['primary_post']


def internal(payload,c,sender):
    if sender!=(c['primary_post'] if c['enabled'] else c['local_post']) or payload.get('generation')!=c['generation']:
        raise HTTPException(403,'Only the current primary can manage site updates')
    action=payload.get('action')
    if action=='status':result=local_status()
    elif action=='job':result=agent(path='/jobs/'+str(UUID(payload['id'])))
    elif action=='install':
        # Independently verify site publication on each station immediately
        # before handing a signed request to the root service.
        envelope=release_current()
        if not envelope or envelope!=payload.get('envelope'):raise HTTPException(409,'release_changed_or_revoked')
        result=agent('POST','/jobs',{'id':str(UUID(payload['id'])),'envelope':envelope})
    else:raise HTTPException(422,'Unknown update action')
    return {'ok':True,'post_no':c['local_post'],**result}


def peer(c,post,payload):
    from .wallet_api import rpc
    request={**payload,'generation':c['generation']}
    result=internal(request,c,c['local_post']) if post==c['local_post'] else rpc(c,post,'software-update',request)
    if result.get('post_no')!=post:raise HTTPException(503,'Peer identity mismatch')
    return result


def release_current():
    from .main import get_license_settings
    ident=get_license_settings()
    if not ident.get('site_code') or not ident.get('site_token'):raise HTTPException(409,'Station activation is required')
    try:
        # One canonical origin: no arbitrary URLs or private credentials in logs.
        with httpx.Client(timeout=10,follow_redirects=False) as client:
            r=client.get('https://pay.labrix.uz/api/v1/software/latest',params={'site_code':ident['site_code'],'post_no':ident['post_no'],'current':0},headers={'X-Site-Token':ident['site_token']})
        r.raise_for_status();envelope=r.json().get('release')
        if envelope:verify_release(envelope,Path('/etc/labrix-updates/signing.pub.pem').read_bytes())
        return envelope
    except (httpx.HTTPError,ValueError,OSError):raise HTTPException(503,'update_server_unavailable_or_signature_invalid') from None


def read_queue():
    with db() as c:row=c.execute('SELECT setting_value FROM app_settings WHERE setting_key=%s',(QUEUE_KEY,)).fetchone()
    return row['setting_value'] if row else None


def save_queue(queue):
    with db() as c:
        c.execute('INSERT INTO app_settings(setting_key,setting_value) VALUES(%s,%s) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()',(QUEUE_KEY,Jsonb(queue)));c.commit()


def public_queue(q):
    if not q:return None
    return {k:q.get(k) for k in ('id','version','release_no','status','posts','created_at','finished_at','error')}


def site_status(c):
    posts=sorted({c['local_post']}|({int(k) for k in c['peer_urls']} if c['enabled'] else set()))
    def collect(post):
        try:return {'post_no':post,'online':True,**peer(c,post,{'action':'status'})}
        except Exception:return {'post_no':post,'online':False,'ok':False,'error':'station_offline_or_old_software'}
    with ThreadPoolExecutor(max_workers=min(8,len(posts))) as pool:return list(pool.map(collect,posts))


@router.get('')
def status(user:Owner):
    c=cfg()
    # Remote Owner is read-only and sees where to manage the site.
    if not manage_allowed(c):
        return {'ok':True,'manage_allowed':False,'primary_post':c['primary_post'],'primary_url':c['peer_urls'].get(str(c['primary_post'])),'posts':[{'post_no':c['local_post'],**local_status()}],'queue':None}
    return {'ok':True,'manage_allowed':True,'primary_post':c['primary_post'],'posts':site_status(c),'queue':public_queue(read_queue())}


@router.get('/notice')
def notice(user:Owner):
    if not manage_allowed(cfg()):return {'available':False}
    info=agent();envelope=release_current()
    available=bool(envelope and envelope['manifest']['release_no']>info['installed'].get('release_no',0))
    return {'available':available,'version':envelope['manifest']['version'] if available else None}


@router.post('/check')
def check(user:Owner):
    c=cfg()
    if not manage_allowed(c):raise HTTPException(403,'Use the current primary station')
    return {'ok':True,'release':release_current()}


class Start(BaseModel):
    model_config=ConfigDict(extra='forbid')
    release_no:int=Field(gt=0)
    password:str=Field(min_length=1,max_length=256)


@router.post('/start')
def start(body:Start,user:Owner):
    if not verify_password(body.password,user['password_hash']):raise HTTPException(403,'Password confirmation failed')
    c=cfg()
    if not manage_allowed(c):raise HTTPException(403,'Use the current primary station')
    if c['enabled'] and (c.get('management_pending') or c.get('single_node') or not c.get('standby_ready')):
        raise HTTPException(409,'Restore wallet redundancy before updating')
    envelope=release_current()
    if not envelope or envelope['manifest']['release_no']!=body.release_no:raise HTTPException(409,'Release changed; check again')
    rows=site_status(c)
    if not any(p.get('ok') and p.get('trusted_key_configured') for p in rows):raise HTTPException(409,'Install the trusted updater on stations first')
    with mutex:
        old=read_queue()
        if old and old['status'] not in TERMINAL:raise HTTPException(409,'An update is already queued')
        queue={'id':str(uuid4()),'version':envelope['manifest']['version'],'release_no':body.release_no,'envelope':envelope,'status':'running','created_at':time.time(),
               'primary_post':c['primary_post'],'generation':c['generation'],'posts':[{'post_no':p['post_no'],'id':str(uuid4()),'status':'waiting'} for p in rows]}
        save_queue(queue)
        with db() as conn:
            conn.execute("INSERT INTO system_events(level,event_type,source,message,context) VALUES('info','software_update_queued','owner',%s,%s)",('Owner approved a site application update',Jsonb({'actor':user['login'],'release_no':body.release_no,'queue_id':queue['id']})));conn.commit()
    ensure_worker()
    return {'ok':True,'queue':public_queue(queue)}


@router.post('/cancel')
def cancel(user:Owner):
    if not manage_allowed(cfg()):raise HTTPException(403,'Use the current primary station')
    with mutex:
        q=read_queue()
        if q and q['status']=='running':
            # Do not interrupt an installation. Only cancel not-yet-started nodes.
            for p in q['posts']:
                if p['status']=='waiting':p['status']='cancelled'
            q['cancel_requested']=True;save_queue(q)
    return {'ok':True}


def tick():
    with mutex:
        q=read_queue()
        if not q or q['status']!='running':return
        c=cfg()
        if c['generation']!=q['generation'] or c['primary_post']!=q['primary_post'] or not manage_allowed(c):
            q.update(status='needs_review',error='wallet_roles_changed');save_queue(q);return
        # Poll the one in-flight installation, including after primary restart.
        pending=next((p for p in q['posts'] if p['status']=='installing'),None)
        if pending:
            try:
                receipt=peer(c,pending['post_no'],{'action':'job','id':pending['id']})
                state=receipt.get('status')
                if state=='completed':pending['status']='completed'
                elif state in ('failed','rolled_back','needs_review'):
                    pending.update(status=state,error=receipt.get('error'));q.update(status='needs_review',error='station_update_failed')
            except Exception as exc:
                # A definite missing receipt means an RPC failed before the
                # root service accepted it. Reuse the same UUID on retry.
                if 'job_not_found' in str(getattr(exc,'detail',exc)):
                    pending.update(status='waiting',reason='request_not_accepted')
                # An installer restart is otherwise expected.

            save_queue(q);return
        waiting=[p for p in q['posts'] if p['status']=='waiting']
        if not waiting:
            q.update(status='cancelled' if q.get('cancel_requested') else 'completed',finished_at=time.time());save_queue(q);return
        # Ordinary posts first, standby next, primary last. The primary waits
        # for every other node, including currently unavailable nodes.
        waiting.sort(key=lambda p:(2 if p['post_no']==c['primary_post'] else 1 if p['post_no']==c.get('standby_post') else 0,p['post_no']))
        candidate=None;info=None
        for row in waiting:
            if row['post_no']==c['primary_post'] and any(p['post_no']!=c['primary_post'] and p['status'] not in ('completed','cancelled') for p in q['posts']):continue
            try:
                value=peer(c,row['post_no'],{'action':'status'})
                if not value.get('ok') or not value.get('trusted_key_configured'):
                    row['reason']='installer_not_installed';continue
                if value.get('installed',{}).get('release_no',0)>=q['release_no']:
                    row['status']='completed';continue
                if not value.get('ready'):row['reason']='station_busy';continue
                candidate=row;info=value;break
            except Exception:row['reason']='station_offline_or_old_software'
        save_queue(q)
        if candidate is None:return
        try:
            if not info.get('ok') or not info.get('trusted_key_configured'):
                candidate['reason']='installer_not_installed';save_queue(q);return
            if info.get('installed',{}).get('release_no',0)>=q['release_no']:
                candidate['status']='completed';save_queue(q);return
            if not info.get('ready'):candidate['reason']='station_busy';save_queue(q);return
            # Persist intent before RPC. A lost acknowledgement is resolved by
            # reading the same idempotent root job on the next loop.
            candidate['status']='installing';candidate.pop('reason',None);save_queue(q)
            peer(c,candidate['post_no'],{'action':'install','id':candidate['id'],'envelope':q['envelope']})
        except Exception:
            if candidate['status']=='waiting':candidate['reason']='station_offline_or_old_software';save_queue(q)
            # If install might have reached the receiver, leave installing and
            # resolve its receipt instead of generating another ID.


def loop():
    while True:
        try:tick()
        except Exception:pass
        time.sleep(15)


def ensure_worker():
    global started
    with mutex:
        if not started:started=True;threading.Thread(target=loop,daemon=True,name='software-update-queue').start()


class Lease(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:UUID


@agent_router.post('/{action}')
def maintenance_lease(action:str,body:Lease,x_update_agent_token:Annotated[str|None,Header()]=None):
    try:secret=Path('/etc/labrix-updates/agent.token').read_text().strip()
    except OSError:raise HTTPException(503,'Local updater is not configured') from None
    if not secret or not hmac.compare_digest(secret,x_update_agent_token or ''):raise HTTPException(403,'Local updater authentication required')
    from .wash_logic import wash_runtime
    from .admin_service import require_idle
    with wash_runtime.lock:
        if action=='prepare':
            require_idle(wash_runtime)
            if wash_runtime.state.get('outputsOffConfirmed') is not True:raise HTTPException(409,'Outputs OFF not confirmed')
            with db() as c:
                row=c.execute("SELECT count(*) n FROM click_payment_intents WHERE status IN ('local_pending','pending','prepared','paid')").fetchone()
                if row['n']:raise HTTPException(409,'Pending Click payment')
            wash_runtime.state.update(softwareUpdateJob=str(body.id),softwareUpdatePendingUntil=time.monotonic()+120)
        elif action=='release':
            if wash_runtime.state.get('softwareUpdateJob')==str(body.id):
                wash_runtime.state.pop('softwareUpdateJob',None);wash_runtime.state.pop('softwareUpdatePendingUntil',None)
        else:raise HTTPException(404,'Unknown maintenance action')
    return {'ok':True}
