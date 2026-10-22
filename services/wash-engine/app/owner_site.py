"""LAN Owner dashboard. Signed peer calls are separate from the wallet journal lock."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC,datetime
from hashlib import sha256
import json
from typing import Annotated,Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from psycopg.types.json import Jsonb
from .auth import require_role
from .db import db
from .site_reporting import aggregate,bounds,local_report

router=APIRouter(prefix='/api/owner/site')
Owner=Annotated[dict,Depends(require_role('owner'))]
Section=Literal['parameters','kiosk','operator']

def revision(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def settings_read(section):
    from .main import wash_runtime,get_kiosk_settings
    from .contact_api import operator_read
    if section=='parameters':value=wash_runtime.snapshot()['parameters']
    elif section=='kiosk':value=get_kiosk_settings()['config']
    elif section=='operator':value=operator_read({})['settings']
    else:raise HTTPException(422,'Unknown settings section')
    return {'value':value,'revision':revision(value)}

def settings_write(section,payload,actor):
    from .main import wash_runtime,owner_save_wash_parameters,save_kiosk_settings
    from .schema import WashParametersRequest,KioskSettingsRequest
    from .contact_api import OperatorSettings,operator_save
    from .admin_service import require_idle
    value=payload.get('value');expected=payload.get('expected_revision')
    if not isinstance(value,dict) or not isinstance(expected,str):raise HTTPException(422,'Value and revision required')
    with wash_runtime.lock:
        if section == "parameters":
            from .dry_fog_purge import cancel
            cancel(wash_runtime)
        require_idle(wash_runtime)
        current=settings_read(section)
        if current['revision']!=expected:raise HTTPException(409,'Settings changed; reload before saving')
        user={'login':actor}
        if section=='parameters':owner_save_wash_parameters(WashParametersRequest(parameters=value),user)
        elif section=='kiosk':
            appearance=(value.get('theme') or {}).get('appearance') or {}
            if appearance.get('mode')=='auto' and appearance.get('lightStart')==appearance.get('lightEnd'):
                raise HTTPException(422,'Light schedule start and end must differ')
            save_kiosk_settings(KioskSettingsRequest(config=value),user)
        elif section=='operator':operator_save(OperatorSettings.model_validate(value),user)
        else:raise HTTPException(422,'Unknown settings section')
        result=settings_read(section)
        with db() as c:
            c.execute("INSERT INTO system_events(level,event_type,source,message,context) VALUES('info','owner_site_settings','owner-site',%s,%s)",
                ('Settings confirmed on target controller',Jsonb({'section':section,'changed_by':actor,'revision':result['revision']})))
            c.commit()
        return {**result,'confirmed':True,'confirmed_at':datetime.now(UTC).isoformat()}

def local_snapshot(start,end):
    from .main import wash_runtime,get_click_settings,require_click_ready,gateway_connectivity
    from .device_setup import local_status
    s=wash_runtime.snapshot()['state'];s.update(gateway_connectivity.snapshot());click=get_click_settings()
    try:require_click_ready(click);click_state='configured' if s['internetOnline'] else 'offline'
    except HTTPException:click_state='disabled' if not click['enabled'] else 'not_ready'
    return {'protocol':1,'checked_at':datetime.now(UTC).isoformat(),'device_type':wash_runtime.device_type,
        'name':local_status()['requested'].get('display_name',''),
        'state':{k:s.get(k) for k in ('creditSum','activeMode','armedMode','phase','lastIoOk','activeSessionId','walletTransferPending','walletCashHeld','internetOnline','internetCheckedAt')},
        'click':click_state,'report':local_report(start,end)}

def internal(payload,cfg,sender):
    if payload.get('generation')!=cfg['generation']:raise HTTPException(409,'Owner site generation changed')
    op=payload.get('action')
    if op=='snapshot':
        bounds(payload.get('date_from'),payload.get('date_to'))
        result=local_snapshot(payload.get('date_from'),payload.get('date_to'))
    elif op=='read':result=settings_read(payload.get('section'))
    elif op=='write':
        if sender!=cfg['primary_post']:raise HTTPException(403,'Only the current primary may change remote settings')
        result=settings_write(payload.get('section'),payload,f"owner@post-{sender}")
    else:raise HTTPException(422,'Unknown Owner site action')
    return {'ok':True,'post_no':cfg['local_post'],**result}

def peer_call(cfg,post,payload):
    from .wallet_api import rpc
    request={**payload,'generation':cfg['generation']}
    if post==cfg['local_post']:return internal(request,cfg,cfg['local_post'])
    result=rpc(cfg,post,'owner-site',request)
    if result.get('post_no')!=post:raise HTTPException(503,'Peer identity mismatch')
    return result

def config():
    from .wallet_api import configuration
    cfg=configuration()
    # A standalone, not-yet-clustered controller still has a useful local Owner.
    return cfg

@router.get('/overview')
def overview(user:Owner,date_from:str|None=None,date_to:str|None=None,device_type:Literal['all','wash','dry_fog']='all',post_no:int|None=Query(default=None,ge=1,le=100)):
    bounds(date_from,date_to);cfg=config()
    posts=sorted({cfg['local_post']}|({int(k) for k in cfg['peer_urls']} if cfg['enabled'] else set()))
    with db() as c:
        row=c.execute("SELECT setting_value FROM app_settings WHERE setting_key='owner_site_last_seen'").fetchone()
    previous=(row or {}).get('setting_value') or {};seen=dict(previous)
    def collect(post):
        try:
            value=peer_call(cfg,post,{'action':'snapshot','date_from':date_from,'date_to':date_to})
            if value.get('protocol')!=1:raise ValueError('Unsupported report protocol')
            return {'post_no':post,'status':'online',**value}
        except Exception:
            # Do not substitute an old report into today's financial totals.
            old=previous.get(str(post),{})
            return {'post_no':post,'status':'offline','checked_at':None,'last_seen_at':old.get('at'),
                'device_type':cfg.get('device_types',{}).get(str(post),old.get('device_type','unknown')),'report':None}
    with ThreadPoolExecutor(max_workers=min(8,len(posts))) as pool:result=list(pool.map(collect,posts))
    for p in result:
        if p['status']=='online':
            p['last_seen_at']=p['checked_at'];seen[str(p['post_no'])]={'at':p['checked_at'],'device_type':p['device_type']}
    # At most one small durable write/minute; never a cached financial total.
    if any(k not in previous or v['at'][:16]!=previous[k].get('at','')[:16] for k,v in seen.items()):
        with db() as c:
            c.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('owner_site_last_seen',%s) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()",(Jsonb(seen),));c.commit()
    if post_no is not None and post_no not in posts:raise HTTPException(404,'Unknown site controller')
    selected=[p for p in result if (device_type=='all' or p['device_type']==device_type) and (post_no is None or p['post_no']==post_no)]
    return {'ok':True,'site_id':cfg['site_id'],'local_post':cfg['local_post'],'primary_post':cfg['primary_post'],
        'standby_post':cfg['standby_post'],'primary_url':cfg['peer_urls'].get(str(cfg['primary_post'])),'manage_allowed':not cfg['enabled'] or cfg['local_post']==cfg['primary_post'],
        'checked_at':datetime.now(UTC).isoformat(),'posts':selected,'inventory':[{k:p.get(k) for k in ('post_no','device_type','name','status')} for p in result],'device_type':device_type,
        **aggregate(selected)}

class SettingsChange(BaseModel):
    expected_revision:str=Field(min_length=64,max_length=64)
    value:dict

def target(post):
    cfg=config()
    if post!=cfg['local_post'] and (not cfg['enabled'] or str(post) not in cfg['peer_urls']):raise HTTPException(404,'Unknown site controller')
    return cfg

@router.get('/posts/{post}/{section}')
def read_settings(post:int,section:Section,user:Owner):
    cfg=target(post)
    try:return peer_call(cfg,post,{'action':'read','section':section})
    except HTTPException:raise
    except Exception:raise HTTPException(503,'Target controller unavailable') from None

@router.post('/posts/{post}/{section}')
def write_settings(post:int,section:Section,payload:SettingsChange,user:Owner):
    cfg=target(post)
    if cfg['enabled'] and cfg['local_post']!=cfg['primary_post']:raise HTTPException(409,'Open the current primary Owner panel to change settings')
    try:
        if post==cfg['local_post']:return {'ok':True,'post_no':post,**settings_write(section,payload.model_dump(),user['login'])}
        return peer_call(cfg,post,{'action':'write','section':section,**payload.model_dump()})
    except HTTPException:raise
    except Exception:
        # A timeout is an unknown outcome, not success and not proof of rollback.
        raise HTTPException(503,'No confirmation from target. Reload its settings before retrying.') from None
