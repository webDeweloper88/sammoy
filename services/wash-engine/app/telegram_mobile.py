"""Short-lived phone handoff for the commissioning wizard; no bot tokens stored here."""
import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import secrets
import time
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
def commissioning_access(client_ip:str|None=Header(default=None,alias='X-Commissioning-Client-IP')):
    from .main import commissioning_access as check
    return check(client_ip)

router=APIRouter()
LOCK=asyncio.Lock()
SESSIONS={}
TTL=600
HEADERS={'Cache-Control':'no-store, max-age=0','Pragma':'no-cache','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}

def guard():
    from . import main
    from .wallet_api import configuration
    from .admin_service import require_idle
    if main.get_commissioning_state().get('complete'):raise HTTPException(403,'Настройка завершена. Используйте Owner → Telegram.')
    require_idle(main.wash_runtime)
    cfg=configuration();identity=main.get_license_settings()
    primary=int(cfg['primary_post']) if cfg['enabled'] else 1
    if int(identity.get('post_no') or 1)!=primary:raise HTTPException(409,'Telegram настраивается на главном посте №'+str(primary))
    if not identity.get('site_code') or main.apply_license_to_runtime().get('locked'):raise HTTPException(409,'Сначала активируйте пост')
    return hashlib.sha256(json.dumps([identity.get('site_code'),identity.get('site_token'),identity.get('post_no'),primary]).encode()).hexdigest()

def lookup(raw,scope):
    key=hashlib.sha256(raw.encode()).hexdigest()
    value=SESSIONS.get(key)
    if not value or value['expires']<=time.time() or value['scope']!=scope or value['attempts']>=5:
        SESSIONS.pop(key,None)
        raise HTTPException(410,'Ссылка недействительна. Создайте новый QR на экране поста.')
    return key,value

class PhoneSession(BaseModel):
    interface:str=Field(pattern='^(eth0|wlan0)$')
    language:str=Field(default='ru',pattern='^(ru|uz|en)$')
class PhoneToken(BaseModel):token:str=Field(min_length=1,max_length=256)

@router.post('/api/commissioning/telegram/mobile/session',dependencies=[Depends(commissioning_access)])
async def create_session(payload:PhoneSession):
    from .main import telegram_setup_request
    from .admin_api import network_request
    scope=guard()
    status=await telegram_setup_request('status')
    if status.get('owner_paired'):raise HTTPException(409,'Бот уже привязан. Изменения доступны в Owner → Telegram.')
    network=await network_request('/status')
    interface=next((i for i in network['interfaces'] if i['interface']==payload.interface and i.get('connected') and i.get('address')),None)
    if not interface:raise HTTPException(409,'Выбранное подключение недоступно. Обновите состояние сети.')
    try:address=ipaddress.IPv4Address(interface['address'])
    except ValueError:raise HTTPException(409,'Нет адреса для подключения телефона') from None
    if not address.is_private or address.is_loopback or address.is_link_local:raise HTTPException(409,'Нужен адрес локальной сети')
    raw=secrets.token_urlsafe(32);expires=time.time()+TTL
    url=f'http://{address}/api/telegram-setup/mobile/{raw}'
    import qrcode
    from qrcode.image.svg import SvgPathImage
    buffer=io.BytesIO();qrcode.make(url,image_factory=SvgPathImage,box_size=8,border=4).save(buffer)
    async with LOCK:
        if any(s.get('busy') for s in SESSIONS.values()):raise HTTPException(409,'Подождите завершения проверки токена')
        SESSIONS.clear()
        SESSIONS[hashlib.sha256(raw.encode()).hexdigest()]={'scope':scope,'expires':expires,'attempts':0,'busy':False,'language':payload.language}
    return {'ok':True,'mobile_url':url,'expires_at':datetime.fromtimestamp(expires,UTC).isoformat(),'qr_data_url':'data:image/svg+xml;base64,'+base64.b64encode(buffer.getvalue()).decode()}

@router.get('/api/telegram-setup/mobile/{raw}',response_class=HTMLResponse)
async def phone_page(raw:str):
    scope=guard()
    async with LOCK:
        _,value=lookup(raw,scope)
        language=value['language']
    nonce=secrets.token_urlsafe(20)
    content=(__import__('pathlib').Path(__file__).with_name('telegram_mobile.html').read_text()
             .replace('__NONCE__',nonce).replace('__LANG__',language))
    return HTMLResponse(content,headers={**HEADERS,'Content-Security-Policy':"default-src 'none'; style-src 'nonce-"+nonce+"'; script-src 'nonce-"+nonce+"'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})

@router.post('/api/telegram-setup/mobile/{raw}/configure')
async def phone_configure(raw:str,payload:PhoneToken):
    from .main import commissioning_telegram_action,telegram_setup_request
    scope=guard()
    async with LOCK:
        key,value=lookup(raw,scope)
        if value['busy']:raise HTTPException(409,'Токен уже проверяется. Подождите.')
        value['busy']=True;value['attempts']+=1
    success=False
    try:
        # Reuses the installer checks: idle, current primary, active license,
        # no replacement of an already paired bot. Never return its token.
        status=await telegram_setup_request('status')
        if status.get('configured'):raise HTTPException(409,'Бот уже подключён. Продолжите на экране поста.')
        result=await commissioning_telegram_action('configure-auto',{'token':payload.token})
        success=True
        return {'ok':True,'bot_username':result.get('bot_username','')}
    finally:
        async with LOCK:
            if success or value['attempts']>=5:SESSIONS.pop(key,None)
            else:value['busy']=False
