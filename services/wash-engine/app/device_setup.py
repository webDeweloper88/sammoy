"""Owner policy is journaled on both wallet authorities; local type is installer-only."""
from copy import deepcopy
from typing import Literal,Annotated
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb
from .auth import require_role
from .db import db
from .wallet_domain import WalletConflict,WalletPolicy
from .wallet_replication import WalletUnavailable

POLICY_UID='@device-policy'
router=APIRouter(prefix='/api')
Owner=Annotated[dict,Depends(require_role('owner'))]

class Award(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    enabled:bool=False
    percent:int=Field(default=10,ge=0,le=100)

class DevicePolicy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    enabled:bool=True
    bonus_mode:Literal['shared','separate']='shared'
    wash_pause_seconds:int=Field(default=60,ge=0,le=86400)
    dry_fog_pause_seconds:int=Field(default=300,ge=0,le=86400)
    device_types:dict[str,Literal['wash','dry_fog']]
    shared:Award=Field(default_factory=Award)
    wash:Award=Field(default_factory=Award)
    dry_fog:Award=Field(default_factory=Award)

class LocalDevice(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    type:Literal['wash','dry_fog']
    display_name:str=Field(default='',max_length=80)


def policy_from_row(row):
    value=(row or {}).get('state',{}).get('service_configuration',{}).get('device_policy')
    return DevicePolicy(**value).model_dump() if value else None


def require_idle(runtime):
    s=runtime.state
    if any(s.get(k) for k in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld')):
        raise WalletConflict('Завершите сеанс и операции карты перед сменой типа или политики')


def local_status():
    from .wash_logic import wash_runtime
    with db() as conn:
        row=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='controller_device'").fetchone()
    return {'ok':True,'active_type':wash_runtime.device_type,'requested':row['setting_value'] if row else {'type':'wash','display_name':''}}


def request_local(value):
    from .wash_logic import wash_runtime
    require_idle(wash_runtime)
    with db() as conn:
        conn.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('controller_device',%s) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()",(Jsonb(value.model_dump()),));conn.commit()
    return {**local_status(),'requires_profile_apply':value.type!=wash_runtime.device_type}


@router.get('/owner/device-policy')
def read_policy(user:Owner):
    from .wallet_client import discover_configuration
    from .wallet_api import rpc
    cfg=discover_configuration()
    return rpc(cfg,cfg['primary_post'],'device-policy-read',{})


@router.post('/owner/device-policy')
def save_policy(value:DevicePolicy,user:Owner):
    from .wallet_api import configuration,authority,control_lock,store_context,coordinator
    from .wallet_client import require_device_wallet_support
    from .wash_logic import wash_runtime
    cfg=configuration();authority(cfg).require_primary()
    try:
        require_idle(wash_runtime)
        if any(not k.isdigit() or str(int(k))!=k or not 1<=int(k)<=100 for k in value.device_types):raise WalletConflict('Некорректные номера устройств')
        if not set(cfg['peer_urls']).issubset(value.device_types):raise WalletConflict('Укажите тип каждого зарегистрированного поста')
        # No self RPC while holding the primary lock.
        require_device_wallet_support(cfg)
        with control_lock,store_context(cfg) as store:
            current=policy_from_row(store.inspect(POLICY_UID))
            if current and current['enabled'] and not value.enabled:
                if store.conn.execute("SELECT 1 FROM shared_wallet_cards WHERE site_id=%s AND state ? 'device_wallet' LIMIT 1",(store.site_id,)).fetchone():
                    raise WalletConflict('Версию 2 нельзя выключить после миграции карт')
            # Changes take effect on new idle sessions; issued bonus groups never move.
            result=coordinator(store,cfg).execute('device-policy:'+uuid4().hex,POLICY_UID,{'action':'configure_service','value':{'device_policy':value.model_dump()},'actor':user['login']},WalletPolicy())
        return {'ok':True,'policy':value.model_dump(),'operation':result}
    except (WalletConflict,WalletUnavailable,ValueError) as exc:raise HTTPException(409,str(exc)) from None


def startup_guard(runtime):
    from .config import settings
    from .wallet_api import configuration
    from .wallet_client import require_device_wallet_support
    if settings.device_type!=runtime.device_type:
        raise RuntimeError('Dry fog requires a commissioned hardware profile and wallet migration')
    cfg=configuration()
    if cfg.get('enabled') and cfg['local_post'] not in (cfg['primary_post'],cfg['standby_post']):
        from .wallet_client import discover_configuration
        cfg=discover_configuration()
    if not cfg.get('device_wallet_enabled') or cfg.get('device_types',{}).get(str(cfg['local_post']))!=runtime.device_type:
        raise RuntimeError('Dry fog device inventory and wallet migration are not commissioned')
    if local_status()['requested']['type']!=runtime.device_type:
        raise RuntimeError('Installer must select the dry-fog type first')
    require_device_wallet_support(cfg,local_capability=True)


def apply_award(runtime,cfg):
    p=cfg.get('device_policy')
    if not p or not p['enabled']:return
    # A policy change applies to the next session, not to already issued credit.
    if any(runtime.state.get(k) for k in ('creditSum','activeSessionId','walletTransferPending','walletCashHeld')):return
    group='shared' if p['bonus_mode']=='shared' else runtime.device_type
    runtime.params['topUpBonus']=deepcopy(p[group])
    runtime.params['bonusDomain']=group
    runtime.params['freePauseSeconds']=p['dry_fog_pause_seconds' if runtime.device_type=='dry_fog' else 'wash_pause_seconds']


def policy_loop(runtime):
    from .wallet_api import configuration
    from .wallet_client import discover_configuration
    while not runtime.stop_event.is_set():
        try:
            cfg=configuration()
            if cfg.get('enabled'):
                if cfg['local_post'] not in (cfg['primary_post'],cfg['standby_post']):cfg=discover_configuration()
                expected=cfg.get('device_types',{}).get(str(cfg['local_post']))
                mismatch=bool(cfg.get('device_wallet_enabled') and expected and expected!=runtime.device_type)
                with runtime.lock:
                    runtime.state['deviceProfileMismatch']=mismatch
                    if mismatch:runtime._io_fault('Device profile does not match the site inventory; installer action required')
                    else:apply_award(runtime,cfg)
                if mismatch:runtime._all_off_sync()
        except Exception:
            # Keep the last confirmed policy; never modify issued money.
            pass
        runtime.stop_event.wait(5)


def fog_kiosk_config(config):
    from .device_profiles import FOG_NAMES
    from .kiosk_defaults import DEFAULT_PROGRAM_STYLE
    labels={**{f'aroma_{i+1}':dict.fromkeys(('uz','kz','ky','ru'),name) for i,name in enumerate(FOG_NAMES)},
            'blackening':dict(zip(('uz','kz','ky','ru'),('SHINA QORAYTIRISH','ШИНАНЫ ҚАРАЙТУ','ДӨҢГӨЛӨКТҮ КАРАЙТУУ','ЧЕРНЕНИЕ ШИН'))),
            'tank_air':dict(zip(('uz','kz','ky','ru'),('SHINANI DAMLASH','ШИНАҒА АУА ҮРЛЕУ','ДӨҢГӨЛӨККӨ АБА ҮЙЛӨӨ','ПОДКАЧКА ШИН')))}
    saved={p['id']:p for p in config.get('programs',[]) if p.get('id') in labels}
    config['programs']=[saved.get(key,{'id':key,'visible':True,'label':label,'style':deepcopy(DEFAULT_PROGRAM_STYLE)}) for key,label in labels.items()]
    if config.get('device',{}).get('type')!='dry_fog':config['brand'].update(name='LABRIX AROMA',productLine='')
    config['device']={'type':'dry_fog'}
    config['theme']['design']='cards'
    return config

@router.get('/owner/device')
def owner_device_read(user:Owner):return local_status()

@router.post('/owner/device')
def owner_device_request(value:LocalDevice,user:Owner):
    try:return request_local(value)
    except WalletConflict as exc:raise HTTPException(409,str(exc)) from None
