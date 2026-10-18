"""Public assistance requests and role-specific contact settings."""
import asyncio
from typing import Annotated
from uuid import UUID
from urllib.parse import urlencode
import httpx,os
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from psycopg.types.json import Jsonb
from .auth import require_role
from .db import db
router=APIRouter()
class OperatorSettings(BaseModel):
    enabled:bool=False
    phone:str=Field(default='',max_length=40,pattern=r'^[+0-9 ()-]*$')
    chat_id:str=Field(default='',max_length=21,pattern=r'^-?[0-9]{1,20}$|^$')
class ManufacturerSettings(BaseModel):
    marketing:str=Field(default='+998 91 111 69 29',max_length=40,pattern=r'^[+0-9 ()-]*$')
    programmer:str=Field(default='+998 91 667 62 28',max_length=40,pattern=r'^[+0-9 ()-]*$')
    electrician:str=Field(default='+998 94 584 13 01',max_length=40,pattern=r'^[+0-9 ()-]*$')
    telegram:str=Field(default='https://t.me/labrixwash',max_length=2048)
    instagram:str=Field(default='https://www.instagram.com/labrixwash/',max_length=2048)
    youtube:str=Field(default='https://www.youtube.com/@labrixwash',max_length=2048)
def read(key,model,conn=None):
    if conn is not None:r=conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=%s',(key,)).fetchone()
    else:
        with db() as c:r=c.execute('SELECT setting_value FROM app_settings WHERE setting_key=%s',(key,)).fetchone()
    return model.model_validate(r['setting_value'] if r else {}).model_dump()
def save(key,model,user):
    value=model.model_dump()
    with db() as c:
        c.execute("INSERT INTO app_settings(setting_key,setting_value,updated_at) VALUES(%s,%s,now()) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()",(key,Jsonb(value)))
        c.execute("INSERT INTO system_events(level,event_type,source,message,context) VALUES('info','contacts_updated','contact-api',%s,%s)",(key,Jsonb({'actor':user['login']})));c.commit()
    return {'ok':True,'settings':value}
@router.get('/api/owner/operator/settings')
def operator_read(user:Annotated[dict,Depends(require_role('owner'))]):return {'ok':True,'settings':read('operator_settings',OperatorSettings)}
@router.post('/api/owner/operator/settings')
def operator_save(payload:OperatorSettings,user:Annotated[dict,Depends(require_role('owner'))]):return save('operator_settings',payload,user)
@router.get('/api/admin/manufacturer/settings')
def manufacturer_read(user:Annotated[dict,Depends(require_role('admin'))]):return {'ok':True,'settings':read('manufacturer_contacts',ManufacturerSettings)}
@router.post('/api/admin/manufacturer/settings')
def manufacturer_save(payload:ManufacturerSettings,user:Annotated[dict,Depends(require_role('admin'))]):
    from urllib.parse import urlsplit
    for link in [payload.telegram,payload.instagram,payload.youtube]:
        if link and (urlsplit(link).scheme!='https' or not urlsplit(link).netloc):raise HTTPException(422,'Social links must use HTTPS')
    return save('manufacturer_contacts',payload,user)
def public_contacts(conn=None):
    operator=read('operator_settings',OperatorSettings,conn)
    return {'operator':{'enabled':operator['enabled'],'phone':operator['phone']},'manufacturer':read('manufacturer_contacts',ManufacturerSettings,conn)}
class CallRequest(BaseModel):request_id:UUID

def setup_call(payload):
    url=os.environ.get('TELEGRAM_SETUP_URL','http://telegram-reports:8076').rstrip('/')
    key=os.environ.get('TELEGRAM_SETUP_KEY','')
    if not key:raise HTTPException(503,'Operator service unavailable')
    try:
        with httpx.Client(timeout=3,trust_env=False) as client:
            if payload.get('action')=='status':r=client.get(url+'/operator/call/'+str(UUID(payload['request_id'])),headers={'Authorization':'Bearer '+key})
            else:r=client.post(url+'/operator/call',headers={'Authorization':'Bearer '+key},json={k:v for k,v in payload.items() if k!='action'})
        data=r.json()
    except (httpx.HTTPError,ValueError):raise HTTPException(503,'Operator service unavailable') from None
    if r.status_code>=400:raise HTTPException(r.status_code,'Operator Telegram is not ready')
    return data

def dispatch(payload):
    from .wallet_api import configuration,rpc
    cfg=configuration()
    if cfg['enabled'] and cfg['local_post']!=cfg['primary_post']:
        # The caller identity comes from the signed site request, not kiosk input.
        return rpc(cfg,cfg['primary_post'],'operator-call',payload)
    return setup_call(payload)
@router.post('/api/kiosk/operator/call')
async def call(payload:CallRequest):
    from .main import get_license_settings
    operator=await asyncio.to_thread(read,'operator_settings',OperatorSettings)
    if not operator['enabled']:raise HTTPException(409,'Operator call is disabled')
    identity=get_license_settings()
    request={'request_id':str(payload.request_id),'post_no':identity['post_no'],'site_id':identity['site_code'],'destination':operator['chat_id']}
    try:return await asyncio.to_thread(dispatch,request)
    except Exception as e:
        from .wallet_replication import WalletUnavailable
        from .wallet_domain import WalletConflict
        if isinstance(e,(WalletUnavailable,WalletConflict)):raise HTTPException(503,'Operator service unavailable') from None
        raise
@router.get('/api/kiosk/operator/call/{request_id}')
async def call_status(request_id:UUID):
    try:return await asyncio.to_thread(dispatch,{'request_id':str(request_id),'action':'status'})
    except Exception as e:
        from .wallet_replication import WalletUnavailable
        from .wallet_domain import WalletConflict
        if isinstance(e,(WalletUnavailable,WalletConflict)):raise HTTPException(503,'Operator service unavailable') from None
        raise
