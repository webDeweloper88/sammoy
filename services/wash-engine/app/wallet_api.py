"""Site-authenticated wallet API and owner controls.

Default disabled. Role changes never happen because of a timeout. Owner promotion
requires physical old-primary fencing plus explicit single-copy acknowledgement.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import hmac
import ipaddress
import json
import threading
import time
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from .http_pool import sync_client
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_role
from .config import settings
from .db import db
from .wallet_domain import WalletConflict, WalletPolicy
from .wallet_replication import Authority, ReplicaReceiver, ReplicatedWallet, WalletUnavailable, promotion_plan
from .wallet_store import WalletStore

router = APIRouter(prefix='/api')
Owner = Annotated[dict, Depends(require_role('owner'))]
Installer = Annotated[dict, Depends(require_role('owner','admin'))]
control_lock = threading.RLock()


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def signature(secret, path, body):
    key=hashlib.sha256(('sammoy-wallet-v1:'+secret).encode()).digest()
    return hmac.new(key,path.encode()+b'\n'+canonical(body),hashlib.sha256).hexdigest()


def validate_peer_url(value):
    parsed=urlsplit(value)
    if parsed.scheme!='http' or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('Peer must be a local HTTP address without credentials/path')
    try:
        addr=ipaddress.ip_address(parsed.hostname or '')
        if not addr.is_private or addr.is_unspecified or addr.is_multicast:
            raise ValueError('Peer must be a private IP')
        parsed.port
    except ValueError:
        raise ValueError('Peer must be a private IP with a valid port') from None
    return value.rstrip('/')


def identity():
    from .main import get_license_settings
    return get_license_settings()


def configuration():
    with db() as conn:
        row=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='shared_wallet'").fetchone()
    ident=identity()
    defaults={'enabled':False,'primary_post':1,'standby_post':None,'generation':1,
              'single_node':False,'standby_ready':False,'visit_timeout_minutes':30,'peer_urls':{},
              'device_wallet_enabled':False,'device_types':{},'bonus_mode':'shared'}
    cfg={**defaults,**(row['setting_value'] if row else {})}
    cfg.update(site_id=str(ident.get('site_code') or ''),local_post=int(ident.get('post_no') or 1))
    if cfg['enabled'] and cfg['site_id']:
        from .device_setup import policy_from_row,POLICY_UID
        with db() as conn:
            row=conn.execute('SELECT state FROM shared_wallet_cards WHERE site_id=%s AND uid=%s',(cfg['site_id'],POLICY_UID)).fetchone()
        policy=policy_from_row(row)
        if policy:cfg.update(device_wallet_enabled=policy['enabled'],device_types=policy['device_types'],bonus_mode=policy['bonus_mode'],device_policy=policy)
    return cfg


def authority(cfg):
    if not cfg['enabled'] or not cfg['site_id'] or not cfg.get('standby_post'):
        raise WalletUnavailable('Shared wallet has not been commissioned')
    return Authority(cfg['site_id'],cfg['local_post'],cfg['primary_post'],cfg['standby_post'],cfg['generation'],cfg['single_node'])


@contextmanager
def store_context(cfg):
    with psycopg.connect(settings.database_url,autocommit=True,row_factory=dict_row,connect_timeout=3) as conn:
        # Session advisory lock spans network round trips. Other processes and
        # role changes must use the same lock, not merely a process-local mutex.
        key='wallet:'+cfg['site_id']
        conn.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(key,))
        try:
            row=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='shared_wallet'").fetchone()
            if row and row['setting_value'].get('enabled') and any(row['setting_value'].get(k)!=cfg.get(k) for k in ('primary_post','standby_post','generation')):
                raise WalletConflict('Wallet authority changed while waiting for the journal lock')
            yield WalletStore(conn,cfg['site_id'])
        finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(key,))


from .wallet_operation import timed_rpc

@timed_rpc
def rpc(cfg, post, action, payload):
    url=cfg['peer_urls'].get(str(post))
    secret=str(identity().get('site_token') or '')
    if not url or not secret:
        raise WalletUnavailable('Peer address or site key is missing')
    path='/api/wallet/internal/'+action
    body={'site_id':cfg['site_id'],'sender_post':cfg['local_post'],
          'timestamp':int(time.time()),'payload':payload}
    try:
        with sync_client(scope='wallet',timeout=4) as client:
            response=client.post(validate_peer_url(url)+path,json=body,
                                 headers={'X-Wallet-Signature':signature(secret,path,body)})
        data=response.json()
        if not hmac.compare_digest(response.headers.get('X-Wallet-Signature',''),signature(secret,path,data)):
            raise WalletUnavailable('Peer response authentication failed')
        if data.pop('request_digest',None)!=hashlib.sha256(canonical(body)).hexdigest():
            raise WalletUnavailable('Peer response belongs to another request')
        if response.status_code>=400:
            error=WalletConflict(str(data.get('detail','Wallet peer rejected request'))) if response.status_code==409 else WalletUnavailable(str(data.get('detail','Wallet peer unavailable')))
            error.definitive=data.get('operation_status')=='not-recorded'
            raise error
        return data
    except (WalletConflict,WalletUnavailable):
        raise
    except (httpx.HTTPError,ValueError):
        raise WalletUnavailable('Wallet peer unavailable') from None


def coordinator(store,cfg):
    auth=authority(cfg)
    return ReplicatedWallet(store,auth,
        lambda payload:rpc(cfg,auth.standby_post,'replica-stage',payload),
        lambda payload:rpc(cfg,auth.standby_post,'replica-commit',payload))


def persist_configuration(cfg,user,action):
    value={key:cfg[key] for key in ('enabled','primary_post','standby_post','generation','single_node','standby_ready','visit_timeout_minutes','peer_urls')}
    with db() as conn:
        conn.execute("""INSERT INTO app_settings(setting_key,setting_value,updated_at) VALUES('shared_wallet',%s,now())
            ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()""",(Jsonb(value),))
        conn.execute("""INSERT INTO system_events(level,event_type,source,message,context)
            VALUES('warning',%s,'wallet-owner',%s,%s)""",(action,action,Jsonb({'actor':user['login'],'primary':cfg['primary_post'],
                'standby':cfg['standby_post'],'generation':cfg['generation'],'single_node':cfg['single_node'],'standby_ready':cfg.get('standby_ready',False)})))
        conn.commit()


class SetupRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    primary_post:int=Field(default=1,ge=1,le=100)
    standby_post:int=Field(ge=1,le=100)
    peer_urls:dict[str,str]
    migrate_local_balances:bool=False
    migration_confirmation:str=Field(default='',max_length=120)
    migrate_local_vip:bool=False
    vip_migration_confirmation:str=Field(default='',max_length=120)


class TimeoutRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    visit_timeout_minutes:int=Field(ge=1,le=1440)


class PromoteRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    old_primary_fenced:bool
    single_node_confirmed:bool
    confirmation:str


@router.get('/owner/wallet')
def owner_status(user:Owner):
    cfg=configuration()
    if not cfg['enabled']:
        return {'ok':True,'configuration':cfg,'role':'not-configured'}
    with control_lock,store_context(cfg) as store:
        counts=store.conn.execute("SELECT count(*) FILTER(WHERE status!='abandoned') AS operations,count(*) FILTER(WHERE status='prepared') AS pending FROM shared_wallet_operations WHERE site_id=%s",(store.site_id,)).fetchone()
    return {'ok':True,'configuration':cfg,'role':'primary' if cfg['local_post']==cfg['primary_post'] else 'standby' if cfg['local_post']==cfg['standby_post'] else 'post',
            'operation_count':counts['operations'],'pending_count':counts['pending'],
            'redundancy':'single-copy' if cfg['single_node'] else 'requires-standby'}


from .schema import CustomerRequest
from pydantic import StrictInt

class LocalImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    uid:str=Field(pattern=r'^[0-9A-Fa-f]{4,64}$')
    amount_sum:StrictInt=Field(gt=0)
    confirmation:str=Field(max_length=150)

@router.get('/owner/wallet/customers')
def customers(user:Owner,after:str='',limit:int=30):
    from .customer_registry import read
    if len(after)>64 or not 1<=limit<=100:raise HTTPException(422,'Invalid registry page')
    try:return read(after.upper(),limit)
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None

@router.post('/owner/wallet/customers')
def customer_save(payload:CustomerRequest,user:Owner):
    from .customer_registry import save
    try:return save(payload,user)
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None

@router.get('/owner/wallet/local-import')
def local_import_preview(user:Owner,after:str='',limit:int=30):
    from .local_balance_import import preview
    if len(after)>64 or not 1<=limit<=100:raise HTTPException(422,'Invalid import page')
    return preview(after.upper(),limit)

@router.post('/owner/wallet/local-import')
def local_import_transfer(payload:LocalImportRequest,user:Owner):
    from .local_balance_import import transfer
    from .wash_logic import wash_runtime
    try:
        with control_lock,wash_runtime.lock:
            if not wash_runtime.shared_wallet_enabled or wash_runtime.state.get('creditSum') or wash_runtime.state.get('requestedOutput') or wash_runtime.state.get('walletTransferPending'):
                raise HTTPException(409,'Включите общий кошелёк и завершите текущий сеанс поста перед переносом')
            prepared=transfer(payload.uid.upper(),payload.amount_sum,payload.confirmation,user,prepare_only=True)
            if prepared.get('already_imported'):return prepared
        # The frozen source cannot be spent; never hold local controller locks
        # across RPC, including RPC back to this same primary.
        return transfer(payload.uid.upper(),payload.amount_sum,payload.confirmation,user)
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None


class VipImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    uid:str=Field(min_length=4,max_length=64,pattern='^[0-9A-Fa-f]+$')
    confirmation:str=Field(max_length=150)

class VipFinishRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirmation:str=Field(max_length=160)

@router.get('/owner/wallet/vip-import')
def vip_import_preview(user:Owner,after:str='',limit:int=30):
    from .vip_migration import preview
    if len(after)>64 or not 1<=limit<=100:raise HTTPException(422,'Invalid VIP page')
    return preview(after.upper(),limit)

@router.post('/owner/wallet/vip-import')
def vip_import_transfer(payload:VipImportRequest,user:Owner):
    from .vip_migration import transfer
    from .wash_logic import wash_runtime
    with control_lock,wash_runtime.lock:
        if not wash_runtime.shared_wallet_enabled or wash_runtime.state.get('creditSum') or wash_runtime.state.get('requestedOutput') or wash_runtime.state.get('walletTransferPending'):
            raise HTTPException(409,'Завершите сеанс поста перед переносом VIP')
    try:return transfer(payload.uid.upper(),payload.confirmation,user)
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None

@router.get('/owner/wallet/vip-migration')
def vip_migration_read(user:Owner):
    from .wallet_client import discover_configuration
    try:
        cfg=discover_configuration()
        return {**rpc(cfg,cfg['primary_post'],'vip-migration-read',{}),'can_finish':cfg['local_post']==cfg['primary_post'],'site_id':cfg['site_id']}
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None

@router.post('/owner/wallet/vip-migration/complete')
def vip_migration_complete(payload:VipFinishRequest,user:Owner):
    from .vip_migration import finish
    try:return finish(user,payload.confirmation)
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None

@router.get('/owner/wallet/diagnostics')
def owner_diagnostics(user:Owner):
    from .wallet_diagnostics import observe,local_proof
    cfg=configuration()
    def snapshot():
        with control_lock,store_context(cfg) as store:return local_proof(cfg,store)
    # Release local locks before contacting another node, including when both
    # Owners inspect their nodes at the same time.
    return observe(cfg,snapshot,lambda post:rpc(cfg,post,'diagnostics',{}))


@router.post('/owner/wallet/timeout')
def owner_timeout(payload:TimeoutRequest,user:Owner):
    with control_lock:
        cfg=configuration();cfg['visit_timeout_minutes']=payload.visit_timeout_minutes
        if cfg['enabled']:
            try:
                authority(cfg).require_primary()
                if not cfg['single_node']:
                    rpc(cfg,cfg['standby_post'],'policy',{'generation':cfg['generation'],'visit_timeout_minutes':payload.visit_timeout_minutes})
            except WalletUnavailable as e:raise HTTPException(409,str(e)) from None
        persist_configuration(cfg,user,'wallet_timeout_changed')
    return {'ok':True,'visit_timeout_minutes':payload.visit_timeout_minutes}


@router.post('/admin/wallet/setup')
def setup(payload:SetupRequest,user:Installer):
    from .wash_logic import wash_runtime
    if payload.primary_post==payload.standby_post:
        raise HTTPException(422,'Главный и резервный посты должны различаться')
    try:peers={str(int(k)):validate_peer_url(v) for k,v in payload.peer_urls.items()}
    except (ValueError,TypeError):raise HTTPException(422,'Укажите номера постов и локальные IP-адреса') from None
    if any(str(post) not in peers for post in (payload.primary_post,payload.standby_post)):
        raise HTTPException(422,'Нужны адреса главного и резервного постов')
    with control_lock,wash_runtime.lock:
        cfg=configuration()
        if not cfg['site_id'] or not identity().get('site_token'):
            raise HTTPException(409,'Сначала завершите активацию мойки и поста')
        if str(cfg['local_post']) not in peers:
            raise HTTPException(422,'Нужен адрес этого поста для подключения к общему кошельку')
        if cfg['enabled']:
            raise HTTPException(409,'Роли установленного кошелька меняются через переключение, не повторную установку')
        if wash_runtime.snapshot()['state'].get('creditSum',0)>0:
            raise HTTPException(409,'На посту есть деньги: установка кошелька запрещена')
        with db() as conn:
            money=conn.execute('SELECT COALESCE(sum(balance_sum),0) AS amount FROM rfid_cards').fetchone()['amount']
            local_vip=conn.execute("SELECT count(*) AS count FROM rfid_cards WHERE card_type='vip'").fetchone()['count']
        if local_vip and (not payload.migrate_local_vip or payload.vip_migration_confirmation!=f"MIGRATE LOCAL VIP POST {cfg['local_post']}"):
            raise HTTPException(409,'Подтвердите сохранение локальных VIP для переноса Owner')
        if money and (not payload.migrate_local_balances or payload.migration_confirmation!=f"MIGRATE LOCAL BALANCES POST {cfg['local_post']}"):
            raise HTTPException(409,'Подтвердите сохранение локальных остатков для переноса Owner')
        with db() as conn:
            try:
                if local_vip:
                    from .vip_migration import stage_all as stage_vip
                    stage_vip(conn,cfg,user)
                if money:
                    from .local_balance_import import stage_all
                    stage_all(conn,cfg,user)
            except WalletConflict as exc:raise HTTPException(409,str(exc)) from None
            conn.commit()
        cfg.update(enabled=True,primary_post=payload.primary_post,standby_post=payload.standby_post,
                   peer_urls=peers,generation=1,single_node=False)
        with store_context(cfg):persist_configuration(cfg,user,'wallet_setup')
        wash_runtime.shared_wallet_enabled=True
    return {'ok':True,'configuration':cfg}


@router.post('/owner/wallet/promote')
def promote(payload:PromoteRequest,user:Owner):
    with control_lock:
        cfg=configuration()
        if payload.confirmation!=f"PROMOTE POST {cfg['local_post']}":
            raise HTTPException(409,'Подтвердите номер поста: PROMOTE POST N')
        try:
            if not cfg.get('standby_ready'):
                raise WalletConflict('Резервный пост ещё не прошёл полную синхронизацию')
            new=promotion_plan(authority(cfg),old_primary_fenced=payload.old_primary_fenced,
                               single_node_confirmed=payload.single_node_confirmed)
            with store_context(cfg) as store:
                # Every staged proposal came from the configured primary. After
                # physical fencing, resolve it before any new spending is allowed.
                for row in store.pending_operations():store.commit_prepared(row['operation_id'])
                cfg.update(primary_post=new.primary_post,standby_post=new.standby_post,
                           generation=new.generation,single_node=True,standby_ready=False)
                persist_configuration(cfg,user,'wallet_primary_promoted')
        except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None
    return {'ok':True,'configuration':cfg,'warning':'Новые операции имеют только одну серверную копию'}


@router.post('/owner/wallet/synchronize')
def synchronize(user:Owner):
    with control_lock:
        cfg=configuration()
        previous_single=cfg['single_node'];sync_started=False
        try:
            authority(cfg).require_primary()
            sync_started=True
            # Rejoin metadata is signed by the current primary; an old node
            # stops serving as primary before importing current journal state.
            rpc(cfg,cfg['standby_post'],'rejoin',{'primary_post':cfg['primary_post'],
                'standby_post':cfg['standby_post'],'generation':cfg['generation'],
                'visit_timeout_minutes':cfg['visit_timeout_minutes'],'peer_urls':cfg['peer_urls']})
            cfg['single_node']=False
            with store_context(cfg) as store:
                pending=rpc(cfg,cfg['standby_post'],'replica-pending',authority(cfg).envelope({}))['operation_ids']
                known=[operation_id for operation_id in pending if store._operation(operation_id) and store._operation(operation_id)['status']!='abandoned']
                rpc(cfg,cfg['standby_post'],'replica-reconcile',authority(cfg).envelope({'operation_ids':known}))
                count=coordinator(store,cfg).catch_up(lambda ids:rpc(cfg,cfg['standby_post'],'replica-summaries',authority(cfg).envelope({'operation_ids':ids}))['summaries'])
                journal_digest,state_digest=store.digest(),store.state_digest()
                ack=rpc(cfg,cfg['standby_post'],'replica-ready',authority(cfg).envelope({'proof_version':2,'digest':journal_digest,'state_digest':state_digest}))
                if ack.get('proof_version')!=2 or ack.get('journal_digest')!=journal_digest or ack.get('state_digest')!=state_digest:
                    raise WalletUnavailable('Standby lacks a matching version-2 state proof; update both nodes')
                cfg['standby_ready']=True
                persist_configuration(cfg,user,'wallet_replication_restored')
        except (WalletConflict,WalletUnavailable) as e:
            if sync_started:
                cfg['standby_ready']=False;cfg['single_node']=previous_single
                persist_configuration(cfg,user,'wallet_proof_failed')
            raise HTTPException(503,str(e)) from None
    return {'ok':True,'operations':count,'configuration':cfg}


@router.post('/wallet/internal/{action}')
def internal(action:str,body:dict,x_wallet_signature:Annotated[str|None,Header()]=None,x_real_ip:Annotated[str|None,Header()]=None):
    cfg=configuration();secret=str(identity().get('site_token') or '')
    path='/api/wallet/internal/'+action
    stamp=body.get('timestamp')
    if not secret or not cfg['enabled'] or body.get('site_id')!=cfg['site_id'] or type(stamp) is not int or abs(time.time()-stamp)>60 or not hmac.compare_digest(x_wallet_signature or '',signature(secret,path,body)):
        raise HTTPException(401,'Invalid site wallet authentication')
    sender=body.get('sender_post')
    if type(sender) is not int or not 1<=sender<=100 or (str(sender) not in cfg['peer_urls'] and action!='enroll'):
        raise HTTPException(403,'Post is not enrolled in the wallet')
    payload=body.get('payload')
    if not isinstance(payload,dict):raise HTTPException(422,'Payload required')
    from fastapi.responses import JSONResponse
    if action=='owner-site':
        # Reports and Owner settings never take the wallet journal/control lock.
        # A slow report must not serialize NFC operations across the site.
        from .owner_site import internal as owner_site_internal
        from pydantic import ValidationError
        code=200
        try:result=owner_site_internal(payload,cfg,sender)
        except HTTPException as exc:code=exc.status_code;result={'detail':exc.detail}
        except ValidationError:code=422;result={'detail':'Invalid settings value'}
        except Exception:code=503;result={'detail':'Owner site service unavailable'}
        result={**result,'request_digest':hashlib.sha256(canonical(body)).hexdigest()}
        return JSONResponse(result,status_code=code,headers={'X-Wallet-Signature':signature(secret,path,result)})
    if action=='operator-call':
        # Notifications must not hold the wallet lock across an HTTP request.
        code=200
        try:
            authority(cfg).require_primary()
            if payload.get('action')!='status' and (payload.get('post_no')!=sender or payload.get('site_id')!=cfg['site_id']):raise WalletConflict('Invalid operator call origin')
            from .contact_api import setup_call
            result=setup_call(payload)
        except (WalletConflict,WalletUnavailable,HTTPException):
            code=503;result={'detail':'Operator service unavailable'}
        result={**result,'request_digest':hashlib.sha256(canonical(body)).hexdigest()}
        return JSONResponse(result,status_code=code,headers={'X-Wallet-Signature':signature(secret,path,result)})
    with control_lock:
        cfg=configuration()
        try:
            if action=='enroll':
                auth=authority(cfg);auth.require_primary()
                url=validate_peer_url(payload.get('url',''))
                if not x_real_ip or ipaddress.ip_address(urlsplit(url).hostname)!=ipaddress.ip_address(x_real_ip):
                    raise WalletConflict('Enrollment address must match the connecting post')
                existing=cfg['peer_urls'].get(str(sender))
                if existing and existing!=url:
                    raise WalletConflict('Этот номер поста уже связан с другим адресом')
                if not existing:
                    peers={**cfg['peer_urls'],str(sender):url}
                    if not cfg['single_node']:
                        rpc(cfg,cfg['standby_post'],'registry',{'generation':cfg['generation'],'peer_urls':peers})
                    with store_context(cfg):
                        cfg['peer_urls']=peers
                        persist_configuration(cfg,{'login':f'post-{sender}'},'wallet_post_enrolled')
                if payload.get('vip_migration_pending'):
                    from .vip_migration import require_nodes,lock_gate
                    require_nodes(cfg)
                    with store_context(cfg) as store:lock_gate(store,cfg,f'post-{sender}')
                result={'ok':True,'bonus_protocol':1,'vip_import_protocol':1,'device_wallet_protocol':2,'device_policy':cfg.get('device_policy'),'device_types':cfg.get('device_types',{}),'device_wallet_enabled':cfg.get('device_wallet_enabled',False),'bonus_mode':cfg.get('bonus_mode','shared'),'primary_post':cfg['primary_post'],'standby_post':cfg['standby_post'],
                        'generation':cfg['generation'],'local_post':cfg['local_post'],'single_node':cfg['single_node']}
            elif action=='registry':
                if sender!=cfg['primary_post'] or payload.get('generation')!=cfg['generation']:
                    raise WalletConflict('Stale post registry sender')
                peers={str(int(k)):validate_peer_url(v) for k,v in payload['peer_urls'].items()}
                with store_context(cfg):
                    cfg['peer_urls']=peers
                    persist_configuration(cfg,{'login':f'post-{sender}'},'wallet_post_registry_synchronized')
                result={'ok':True}
            elif action=='rejoin':
                current=sender==cfg['primary_post'] and payload.get('generation')==cfg['generation']
                promoted=sender==cfg['standby_post'] and payload.get('generation')==cfg['generation']+1
                if not (current or promoted) or payload.get('primary_post')!=sender or payload.get('standby_post')!=cfg['local_post']:
                    raise WalletConflict('Invalid primary rejoin announcement')
                with store_context(cfg):
                    cfg.update(primary_post=sender,standby_post=cfg['local_post'],generation=payload['generation'],
                               single_node=False,standby_ready=False,visit_timeout_minutes=payload['visit_timeout_minutes'],
                               peer_urls={str(int(k)):validate_peer_url(v) for k,v in payload.get('peer_urls',cfg['peer_urls']).items()})
                    persist_configuration(cfg,{'login':f'post-{sender}'},'wallet_node_rejoined')
                result={'ok':True}
            elif action=='policy':
                if sender!=cfg['primary_post'] or payload.get('generation')!=cfg['generation']:
                    raise WalletConflict('Stale policy sender')
                minutes=WalletPolicy(visit_timeout_minutes=payload.get('visit_timeout_minutes')).visit_timeout_minutes
                with store_context(cfg):
                    cfg['visit_timeout_minutes']=minutes
                    persist_configuration(cfg,{'login':f'post-{sender}'},'wallet_policy_synchronized')
                result={'ok':True}
            elif action=='vip-import-status':
                from .vip_migration import source_status
                result=source_status()
            elif action=='status':
                if payload.get('vip_migration_pending'):
                    from .vip_migration import require_nodes,lock_gate
                    require_nodes(cfg)
                    with store_context(cfg) as store:lock_gate(store,cfg,f'post-{sender}')
                result={'ok':True,'bonus_protocol':1,'vip_import_protocol':1,'device_wallet_protocol':2,'device_policy':cfg.get('device_policy'),'device_types':cfg.get('device_types',{}),'device_wallet_enabled':cfg.get('device_wallet_enabled',False),'bonus_mode':cfg.get('bonus_mode','shared'),'primary_post':cfg['primary_post'],'standby_post':cfg['standby_post'],
                        'generation':cfg['generation'],'local_post':cfg['local_post'],'single_node':cfg['single_node'],'standby_ready':cfg.get('standby_ready',False)}
            else:
                auth=authority(cfg)
                with store_context(cfg) as store:
                    if action=='device-policy-read':
                        result={'ok':True,'policy':cfg.get('device_policy'),'configuration':{k:cfg[k] for k in ('primary_post','local_post','peer_urls')}}
                    elif action=='diagnostics':
                        from .wallet_diagnostics import local_proof
                        result=local_proof(cfg,store)
                    elif action=='replica-stage':result=ReplicaReceiver(store,auth).stage(payload)
                    elif action=='replica-commit':result=ReplicaReceiver(store,auth).commit(payload)
                    elif action=='replica-pending':
                        auth.require_replica_sender(payload);result={'operation_ids':[r['operation_id'] for r in store.pending_operations()]}
                    elif action=='replica-reconcile':
                        auth.require_replica_sender(payload);store.reconcile_pending(payload['payload']['operation_ids']);result={'ok':True}
                    elif action=='replica-summaries':
                        auth.require_replica_sender(payload);result={'summaries':store.summaries(payload['payload']['operation_ids'])}
                    elif action=='replica-manifest':
                        auth.require_replica_sender(payload)
                        store.reconcile_manifest(payload['payload']['operation_ids']);result={'ok':True}
                    elif action=='replica-ready':
                        auth.require_replica_sender(payload)
                        if payload['payload'].get('proof_version')!=2 or store.pending_operations() or store.digest()!=payload['payload']['digest'] or store.state_digest()!=payload['payload'].get('state_digest'):
                            cfg['standby_ready']=False
                            persist_configuration(cfg,{'login':f'post-{sender}'},'wallet_proof_failed')
                            raise WalletConflict('Standby journal or materialized state does not match')
                        cfg['standby_ready']=True
                        persist_configuration(cfg,{'login':f'post-{sender}'},'wallet_standby_ready')
                        result={'ok':True,'proof_version':2,'journal_digest':store.digest(),'state_digest':store.state_digest()}
                    elif action=='execute':
                        auth.require_primary()
                        expected=payload.get('expected_authority')
                        if expected is not None and expected!={k:cfg[k] for k in ('primary_post','generation')}:
                            raise WalletConflict('Wallet authority changed during card operation')
                        command=payload.get('command',{})
                        allowed={'reserve_load','accept_load','open_post','checkpoint','prepare_return','complete_return','register_payment','wallet_credit','grant_vip','checkpoint_vip','return_vip'}
                        if command.get('post_no')!=sender or command.get('action') not in allowed:
                            raise WalletConflict('Command is not permitted for this post endpoint')
                        if 'wallet_protocol' in command:
                            if command.get('wallet_protocol')!=2 or not cfg.get('device_wallet_enabled'):
                                raise WalletConflict('Device wallet has not been commissioned')
                            expected=cfg.get('device_types',{}).get(str(sender),'wash')
                            if command.get('device_type')!=expected:
                                raise WalletConflict('Post device type differs from commissioned inventory')
                            from .wallet_client import require_device_wallet_support
                            require_device_wallet_support(cfg,local_capability=True)
                        if command.get('action')=='grant_vip':
                            from .vip_migration import guard_grant
                            guard_grant(store,cfg)
                            from .wallet_registry import profile_value
                            card=store.inspect(payload['uid'])
                            profile_id=(card['state'].get('vip_profile') or {}).get('id') if card else None
                            command={**command,'profile_override':next((p for p in profile_value(store) if p['id']==profile_id),None)}
                            existing=store._operation(payload['operation_id'])
                            if existing:
                                old={k:v for k,v in existing['command'].items() if k!='profile_override'}
                                incoming={k:v for k,v in command.items() if k!='profile_override'}
                                if old!=incoming:raise WalletConflict('Operation ID reused with different contents')
                                command=existing['command']
                        from .wash_logic import wash_runtime
                        if command.get('wallet_protocol')==2:
                            from .wallet_devices import site_policy
                            policy=site_policy(cfg)
                        else:
                            policy=WalletPolicy(cfg['visit_timeout_minutes'],int(wash_runtime.params['freePauseSeconds']*1000),int(wash_runtime.params['tariffs']['water']['amountSum']),int(wash_runtime.params['tariffs']['water']['durationSeconds']))
                        result=coordinator(store,cfg).execute(payload['operation_id'],payload['uid'],command,policy)
                    elif action=='customer-registry':
                        auth.require_primary()
                        from .customer_registry import page
                        after=payload.get('after','');limit=payload.get('limit',30)
                        if not isinstance(after,str) or len(after)>64 or type(limit) is not int or not 1<=limit<=100:
                            raise WalletConflict('Invalid customer registry page')
                        result=page(store,after,limit)
                    elif action=='import-vip':
                        auth.require_primary()
                        from .vip_migration import import_on_primary
                        result=import_on_primary(store,cfg,payload,sender)
                    elif action=='vip-migration-read':
                        auth.require_primary()
                        from .vip_migration import GATE_UID
                        gate=store.inspect(GATE_UID)
                        result={'ok':True,'complete':bool(gate and not gate['pending_operation'] and gate['state']['service_configuration'].get('complete')), 'configuration':gate['state']['service_configuration'] if gate else {}}
                    elif action=='import-local':
                        auth.require_primary()
                        from uuid import UUID
                        import re
                        command=payload.get('command',{});uid=payload.get('uid');operation=payload.get('operation_id')
                        try:valid_id=isinstance(operation,str) and operation.startswith('local-import:') and str(UUID(operation[13:]))==operation[13:]
                        except (ValueError,TypeError):valid_id=False
                        if not valid_id or not isinstance(uid,str) or not re.fullmatch('[0-9A-F]{4,64}',uid) or not isinstance(command,dict) or command.get('action')!='import_local_balance' or command.get('post_no')!=sender or command.get('receipt_id')!=operation:
                            raise WalletConflict('Invalid local import identity')
                        result=coordinator(store,cfg).execute(operation,uid,command,WalletPolicy(cfg['visit_timeout_minutes']))
                    elif action=='registry-read':
                        auth.require_primary()
                        from .wallet_registry import registry_payload
                        result=registry_payload(store)
                    elif action=='inspect':
                        auth.require_primary();result={'ok':True,'card':store.inspect(payload['uid'])}
                    else:raise WalletConflict('Unknown wallet action')
        except (WalletConflict,WalletUnavailable,KeyError,ValueError) as e:
            result={'detail':str(e),'request_digest':hashlib.sha256(canonical(body)).hexdigest()}
            if action=='execute' and isinstance(e,WalletConflict) and payload.get('operation_id'):
                with store_context(cfg) as check:
                    operation=check._operation(payload['operation_id'])
                    result['operation_status']=operation['status'] if operation else 'not-recorded'
            return JSONResponse(result,status_code=409 if isinstance(e,WalletConflict) else 503,
                                headers={'X-Wallet-Signature':signature(secret,path,result)})
    result={**result,'request_digest':hashlib.sha256(canonical(body)).hexdigest()}
    return JSONResponse(result,headers={'X-Wallet-Signature':signature(secret,path,result)})

@router.get('/admin/wallet')
def admin_wallet_status(user:Installer):
    return owner_status(user)

def registry_bridge(function,*args):
    try:return function(*args)
    except (WalletConflict,WalletUnavailable) as e:raise HTTPException(409,str(e)) from None


@router.post('/wallet/report-claim')
def report_claim(payload:dict,authorization:Annotated[str|None,Header()]=None):
    import os
    from zoneinfo import ZoneInfo
    secret=os.environ.get('TELEGRAM_SETUP_KEY','')
    if not secret or not hmac.compare_digest(authorization or '', 'Bearer '+secret):
        raise HTTPException(401,'Report service authentication required')
    cfg=configuration()
    if not cfg['enabled']:return {'ok':True,'allowed':True}
    day=datetime.now(ZoneInfo('Asia/Tashkent')).date().isoformat()
    if payload.get('day')!=day:raise HTTPException(422,'Report day must match site time')
    with control_lock,store_context(cfg) as store:
        try:
            authority(cfg).require_primary()
            op='telegram:daily:'+day
            existed=store._operation(op) is not None
            coordinator(store,cfg).execute(op,'@telegram-reports',{'action':'configure_service','value':{'day':day,'reserved':True}},WalletPolicy(cfg['visit_timeout_minutes']))
        except (WalletUnavailable,WalletConflict) as e:raise HTTPException(503,str(e)) from None
    return {'ok':True,'allowed':not existed,'delivery_policy':'at-most-once automatic attempt; request a manual report if delivery was uncertain'}


class RecoveryRequest(BaseModel):
    model_config=ConfigDict(strict=True)
    uid:str=Field(min_length=4,max_length=64,pattern=r'^[0-9A-Fa-f]+$')


@router.get('/owner/wallet/recovery')
def wallet_recovery_list(user:Owner):
    with db() as conn:
        rows=conn.execute("SELECT r.id,r.wash_session_id,r.amount_sum,r.reason,r.created_at,r.metadata->>'wallet_target_uid' AS target_uid FROM recovery_credits r JOIN wash_sessions s ON s.id=r.wash_session_id WHERE r.status='unclaimed' AND s.source IS DISTINCT FROM 'vip' ORDER BY r.id DESC LIMIT 100").fetchall()
    return {'credits':rows}


@router.post('/owner/wallet/recovery/{recovery_id}')
def wallet_recovery_restore(recovery_id:int,payload:RecoveryRequest,user:Owner):
    from .wallet_payments import restore_recovery
    from .wash_logic import wash_runtime
    try:
        with wash_runtime.lock:
            return restore_recovery(recovery_id,payload.uid.upper(),str(user['login']))
    except (WalletConflict,WalletUnavailable) as exc:raise HTTPException(409,str(exc)) from None
