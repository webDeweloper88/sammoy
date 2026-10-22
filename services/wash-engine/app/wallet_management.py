"""Explicit, resumable authority changes. Never promotes on a timeout."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import UTC, datetime
import threading
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from .auth import bearer, require_role
from .security import decode_access_token
from .wallet_domain import WalletConflict
from .wallet_replication import Authority, ReplicatedWallet, WalletUnavailable

router=APIRouter(prefix='/api/wallet-management')
Operator=Annotated[dict,Depends(require_role('owner','admin'))]
worker_lock=threading.Lock()
FIELDS=('primary_post','standby_post','generation')
REPLICA_ACTIONS=frozenset(('replica-stage','replica-commit','replica-pending',
                           'replica-reconcile','replica-summaries','replica-manifest','replica-ready'))


class ManagementBusy(RuntimeError):pass


@contextmanager
def distributed():
    key='wallet-management:'+api().configuration()['site_id']
    with api().db() as conn:
        locked=conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked',(key,)).fetchone()['locked']
        if not locked:raise ManagementBusy('Дождитесь завершения текущего этапа')
        try:yield
        finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(key,))


def running():
    if worker_lock.locked():return True
    try:
        with distributed():return False
    except ManagementBusy:return True


class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    kind:Literal['replace_standby','handover']
    target_post:int=Field(ge=1,le=100)
    target_url:str=Field(default='',max_length=200)
    old_standby_fenced:bool=False


class Change(Selection):
    request_id:UUID=Field(strict=False)
    expected_authority:dict[str,int]


class Resume(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID=Field(strict=False)


def api():
    from . import wallet_api
    return wallet_api


def roles(cfg):return {k:cfg[k] for k in FIELDS}


def same_proof(left,right):
    if not isinstance(left,dict) or not isinstance(right,dict):return False
    keys=('journal_digest','state_digest','operation_count')
    if any(type(p.get(k)) is not int or p[k]<0 for p in (left,right) for k in ('pending_count','operation_count')):return False
    return (left.get('proof_version')==right.get('proof_version')==2
            and left.get('pending_count')==right.get('pending_count')==0
            and all(left.get(k)==right.get(k) for k in keys)
            and all(isinstance(left.get(k),str) and len(left[k])==64 for k in keys[:2]))


def validate_transition(payload):
    if payload.get('kind') not in ('replace_standby','handover'):raise WalletConflict('Неизвестное изменение ролей')
    for name in ('before','after'):
        value=payload.get(name)
        if not isinstance(value,dict) or set(value)!=set(FIELDS):raise WalletConflict('Неполные роли постов')
        if any(type(value.get(k)) is not int or value[k]<1 for k in FIELDS):raise WalletConflict('Некорректные роли постов')
        if value['primary_post']==value['standby_post'] or max(value['primary_post'],value['standby_post'])>100:
            raise WalletConflict('Главный и резервный должны быть разными постами')
    before,after=payload['before'],payload['after'];target=payload.get('target_post')
    if type(target) is not int or not 1<=target<=100 or after['generation']!=before['generation']+1:
        raise WalletConflict('Некорректная последовательность смены ролей')
    expected=({'primary_post':before['primary_post'],'standby_post':target} if payload['kind']=='replace_standby'
              else {'primary_post':before['standby_post'],'standby_post':before['primary_post']})
    if any(after[k]!=v for k,v in expected.items()) or (payload['kind']=='handover' and target!=before['standby_post']):
        raise WalletConflict('План смены ролей не совпадает')
    peers=payload.get('peer_urls')
    if not isinstance(peers,dict) or any(str(after[k]) not in peers for k in ('primary_post','standby_post')):
        raise WalletConflict('Не заданы адреса новых ролей')
    for url in peers.values():api().validate_peer_url(url)
    if not isinstance(payload.get('actor'),str) or not payload['actor'] or len(payload['actor'])>80:
        raise WalletConflict('Не указана учётная запись установщика')


def local_proof(cfg):
    a=api()
    with a.store_context(cfg,allow_management=True) as store:return store.diagnostics()


def idle():
    from .admin_service import require_idle
    from .wash_logic import wash_runtime
    with wash_runtime.lock:require_idle(wash_runtime)


def fresh_candidate(cfg):
    if cfg.get('enabled'):return
    from .main import get_commissioning_state,apply_license_to_runtime
    if get_commissioning_state().get('complete') or apply_license_to_runtime().get('locked'):
        raise WalletConflict('Активируйте новый пост и оставьте мастер установки открытым')
    with api().db() as conn:
        row=conn.execute("SELECT count(*) FILTER (WHERE balance_sum<>0) AS amount,count(*) FILTER (WHERE card_type='vip') AS vip FROM rfid_cards").fetchone()
    if row['amount'] or row['vip']:
        raise WalletConflict('На выбранном посту есть локальные деньги или VIP. Сначала выполните перенос с установщиком.')


def probe(cfg):
    fresh_candidate(cfg)
    idle()
    return {'ok':True,'management_protocol':1,'local_post':cfg['local_post'],
            **roles(cfg),'standby_ready':cfg.get('standby_ready',False),
            'wallet_enabled':cfg.get('enabled',False),
            'management_pending':bool(cfg.get('management_pending')),
            'proof':local_proof(cfg)}


def remote(cfg,post,action,payload):
    return api().rpc(cfg,post,'management-'+action,payload)


def require_disconnected(cfg,post,label='резерв'):
    try:remote(cfg,post,'probe',{})
    except WalletUnavailable:return  # Physical isolation remains an operator duty.
    except WalletConflict:pass      # An authenticated rejection still proves life.
    raise WalletConflict(f'Прежний {label} отвечает. Снимите отметку об отключении или физически отключите его.')


def preflight(cfg,selection):
    a=api()
    if not cfg.get('enabled') or cfg['local_post']!=cfg['primary_post']:
        raise WalletConflict('Откройте этот раздел на текущем главном посту')
    if cfg.get('management_pending'):raise WalletConflict('Сначала завершите текущее изменение ролей')
    idle()
    target=selection.target_post
    if target==cfg['primary_post']:raise WalletConflict('Выберите другой пост')
    next_roles={**roles(cfg),'generation':cfg['generation']+1}
    peers=dict(cfg['peer_urls'])
    if selection.kind=='handover':
        if target!=cfg['standby_post'] or not cfg.get('standby_ready') or cfg.get('single_node'):
            raise WalletConflict('Передать управление можно только проверенному действующему резерву. Сначала замените резерв и синхронизируйте его.')
        next_roles.update(primary_post=target,standby_post=cfg['primary_post'])
    else:
        if target==cfg['standby_post'] and cfg.get('standby_ready'):raise WalletConflict('Этот пост уже назначен резервным')
        url=a.validate_peer_url(selection.target_url or peers.get(str(target),''))
        if any(url==address for number,address in peers.items() if number!=str(target)):
            raise WalletConflict('Этот адрес уже принадлежит другому посту')
        peers[str(target)]=url;next_roles['standby_post']=target
    candidate=remote({**cfg,'peer_urls':peers},target,'probe',{})
    if candidate.get('management_protocol')!=1 or candidate.get('local_post')!=target:
        raise WalletConflict('Обновите выбранный пост: нужна поддержка управления резервом')
    if candidate.get('management_pending'):raise WalletConflict('На выбранном посту не завершено предыдущее изменение ролей')
    proof=local_proof(cfg)
    if proof.get('pending_count') or candidate['proof'].get('pending_count'):
        raise WalletConflict('Сначала завершите незавершённые операции кошелька')
    if selection.kind=='handover':
        if roles(candidate)!=roles(cfg) or not same_proof(proof,candidate['proof']):
            raise WalletConflict('Данные резерва не совпадают. Выполните синхронизацию и повторите проверку.')
    else:
        if candidate.get('standby_ready') or (candidate.get('wallet_enabled') is not False and candidate.get('primary_post')!=cfg['primary_post']):
            raise WalletConflict('Выбранный пост уже участвует в других ролях. Требуется проверка установщика.')
        if target!=cfg['standby_post'] and selection.old_standby_fenced:
            require_disconnected(cfg,cfg['standby_post'])
        if target!=cfg['standby_post'] and not selection.old_standby_fenced:
            old=remote(cfg,cfg['standby_post'],'probe',{})
            if old.get('management_protocol')!=1 or roles(old)!=roles(cfg) or not same_proof(proof,old['proof']):
                raise WalletConflict('Проверьте действующий резерв. Если он неисправен, физически отключите его и подтвердите отключение.')
    return {'ok':True,'before':roles(cfg),'after':next_roles,'peer_urls':peers,'target_post':target}


def persist(cfg,job,event):
    cfg['management_pending']=deepcopy(job)
    api().persist_configuration(cfg,{'login':job['actor']},event)


def proof_ready(cfg,job):
    a=api();auth=Authority(cfg['site_id'],cfg['local_post'],cfg['primary_post'],cfg['standby_post'],cfg['generation'],False)
    with a.store_context(a.configuration(),allow_management=True) as store:
        if store.pending_operations():raise WalletConflict('Есть незавершённые операции. Переключение остановлено.')
        wallet=ReplicatedWallet(store,auth,
            lambda payload:a.rpc(cfg,cfg['standby_post'],'replica-stage',payload),
            lambda payload:a.rpc(cfg,cfg['standby_post'],'replica-commit',payload))
        wallet.catch_up(lambda ids:a.rpc(cfg,cfg['standby_post'],'replica-summaries',auth.envelope({'operation_ids':ids}))['summaries'])
        left=store.diagnostics()
        right=remote(cfg,cfg['standby_post'],'probe',{})['proof']
        if not same_proof(left,right):raise WalletConflict('Журнал или остатки нового резерва не совпадают. Данные не удалены.')
        return left


def run_job(request_id):
    a=api()
    try:
        with a.control_lock,distributed():
            cfg=a.configuration();job=cfg.get('management_pending')
            if not job or job['request_id']!=request_id:return
            job['error']=None;job.pop('error_code',None);persist(cfg,job,'wallet_role_change_resumed')
            if job['stage']=='checking':
                idle()
                if local_proof(cfg).get('pending_count'):raise WalletConflict('Сначала завершите операции кошелька')
                remote({**cfg,'peer_urls':job['peer_urls']},job['target_post'],'prepare',job)
                job['stage']='copying';persist(cfg,job,'wallet_role_change_prepared')
            if job['stage']=='copying':
                if job['kind']=='replace_standby':
                    next_cfg={**cfg,**job['after'],'single_node':False,'peer_urls':job['peer_urls']}
                    job['proof']=proof_ready({**next_cfg,'generation':job['after']['generation']},job)
                else:
                    left=local_proof(cfg);right=remote({**cfg,'peer_urls':job['peer_urls']},job['target_post'],'probe',{})['proof']
                    if not same_proof(left,right):raise WalletConflict('Данные изменились до передачи. Переключение остановлено.')
                    job['proof']=left
                job['stage']='retiring';persist(cfg,job,'wallet_role_change_verified')
            if job['stage']=='retiring':
                if job['kind']=='replace_standby' and job['before']['standby_post']!=job['target_post'] and job['old_standby_fenced']:
                    require_disconnected(cfg,job['before']['standby_post'])
                if job['kind']=='replace_standby' and job['before']['standby_post']!=job['target_post'] and not job['old_standby_fenced']:
                    remote(cfg,job['before']['standby_post'],'retire',job)
                job['stage']='committing';persist(cfg,job,'wallet_role_change_old_reserve_retired')
            if job['stage']=='committing':
                cfg.update(**job['after'],peer_urls=job['peer_urls'],standby_ready=False,single_node=False)
                job['stage']='activating';persist(cfg,job,'wallet_role_change_local_committed')
            if job['stage']=='activating':
                result=remote(cfg,job['target_post'],'activate',job)
                if result.get('request_id')!=request_id or result.get('authority')!=job['after']:
                    raise WalletConflict('Не получено подтверждение новых ролей')
                cfg['standby_ready']=True;cfg['management_last']={**job,'stage':'completed','error':None}
                cfg['management_pending']=None
                a.persist_configuration(cfg,{'login':job['actor']},'wallet_role_change_completed')
    except ManagementBusy:pass
    except Exception as error:
        try:
            with a.control_lock,distributed():
                cfg=a.configuration();job=cfg.get('management_pending')
                if job and job.get('request_id')==request_id:
                    job['error']='Изменение не завершено. Проверьте связь и продолжите проверку. Операции кошелька приостановлены.'
                    job['error_code']='old_standby_online' if isinstance(error,WalletConflict) and str(error).startswith('Прежний резерв отвечает') else 'verification_incomplete'
                    persist(cfg,job,'wallet_role_change_interrupted')
        except ManagementBusy:pass
    finally:worker_lock.release()


def internal(action,payload,cfg,sender):
    a=api()
    if action=='probe':return probe(cfg)
    validate_transition(payload)
    if sender!=payload.get('before',{}).get('primary_post') or sender==cfg['local_post']:
        raise WalletConflict('Изменение должен начать прежний главный пост')
    job_id=str(UUID(payload['request_id']))
    last=cfg.get('management_last') or {}
    if last.get('request_id')==job_id and action!='abort':
        return {'ok':True,'request_id':job_id,'authority':roles(cfg)}
    current=cfg.get('management_pending')
    if current and current.get('request_id')!=job_id:raise WalletConflict('Другое изменение ролей уже выполняется')
    if action=='abort':
        if last.get('request_id')==job_id and last.get('stage')=='completed':raise WalletConflict('Роли уже включены; отмена запрещена')
        if not current:return {'ok':True,'request_id':job_id}
        if current.get('stage')!='prepared':raise WalletConflict('Переключение уже началось; продолжите проверку')
        original=current['original_configuration']
        original['management_pending']=None;original['management_last']={**payload,'stage':'aborted'}
        a.persist_configuration(original,{'login':payload['actor']},'wallet_role_change_target_aborted')
        return {'ok':True,'request_id':job_id}
    if action=='prepare':
        if current:return {'ok':True,'request_id':job_id}
        idle()
        fresh_candidate(cfg)
        if cfg.get('enabled') and cfg['primary_post']!=sender:raise WalletConflict('Прежний главный не совпадает')
        if payload['target_post']!=cfg['local_post']:raise WalletConflict('Выбран другой пост')
        if payload['after']['generation']<=cfg['generation']:raise WalletConflict('Устаревшее изменение ролей')
        if local_proof(cfg).get('pending_count'):raise WalletConflict('Есть незавершённые операции')
        if payload['kind']=='replace_standby':
            if cfg.get('standby_ready'):raise WalletConflict('Пост уже является готовым резервом')
        elif roles(cfg)!=payload['before'] or not cfg.get('standby_ready'):
            raise WalletConflict('Передача разрешена только действующему проверенному резерву')
        job={**payload,'stage':'prepared','original_configuration':deepcopy(cfg)}
        if payload['kind']=='replace_standby':cfg.update(**payload['after'],enabled=True,single_node=False,peer_urls=payload['peer_urls'])
        cfg['standby_ready']=False;persist(cfg,job,'wallet_role_change_target_prepared')
        return {'ok':True,'request_id':job_id}
    if action=='retire':
        if cfg['local_post']!=payload['before']['standby_post'] or roles(cfg)!=payload['before']:
            raise WalletConflict('Прежний резерв или роли не совпадают')
        idle()
        cfg.update(**payload['after'],peer_urls=payload['peer_urls'],standby_ready=False,single_node=False)
        cfg['management_last']={**payload,'stage':'retired'};cfg['management_pending']=None
        a.persist_configuration(cfg,{'login':payload['actor']},'wallet_old_standby_retired')
        return {'ok':True,'request_id':job_id,'authority':roles(cfg)}
    if action=='activate':
        if not current or current.get('stage')!='prepared' or current.get('after')!=payload['after']:
            raise WalletConflict('Выбранный пост не подготовлен')
        if not same_proof(local_proof(cfg),payload['proof']):raise WalletConflict('Данные изменились; активация остановлена')
        cfg.update(**payload['after'],peer_urls=payload['peer_urls'],standby_ready=True,single_node=False)
        cfg['management_pending']=None;cfg['management_last']={**payload,'stage':'completed'}
        a.persist_configuration(cfg,{'login':payload['actor']},'wallet_role_change_target_activated')
        return {'ok':True,'request_id':job_id,'authority':roles(cfg)}
    raise WalletConflict('Неизвестное действие управления постами')


class Recovery(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    old_primary_fenced:bool
    single_copy_accepted:bool


@router.post('/recover')
def recover(value:Recovery,user:Operator,credentials:Annotated[HTTPAuthorizationCredentials,Depends(bearer)]):
    fresh(credentials);idle();a=api();cfg=a.configuration()
    if cfg.get('management_pending'):raise HTTPException(409,'Сначала завершите изменение ролей')
    if cfg['local_post']!=cfg.get('standby_post') or not cfg.get('standby_ready'):
        raise HTTPException(409,'Восстановление доступно только проверенному резервному посту')
    if not value.old_primary_fenced or not value.single_copy_accepted:
        raise HTTPException(409,'Подтвердите отключение прежнего главного и работу с одной копией')
    try:require_disconnected(cfg,cfg['primary_post'],'главный')
    except WalletConflict as error:raise HTTPException(409,str(error)) from None
    return a.promote(a.PromoteRequest(old_primary_fenced=value.old_primary_fenced,
        single_node_confirmed=value.single_copy_accepted,
        confirmation=f"PROMOTE POST {cfg['local_post']}"),user)


def fresh(credentials):
    claims=decode_access_token(credentials.credentials)
    if not 0<=time.time()-int(claims.get('iat',0))<=60:raise HTTPException(401,'Повторно введите пароль для подтверждения')


@router.get('/status')
def status(user:Operator):
    cfg=api().configuration()
    missing=[int(p) for p in cfg.get('peer_urls',{}) if cfg.get('device_wallet_enabled') and str(p) not in cfg.get('device_types',{})]
    return {'ok':True,'running':bool(cfg.get('management_pending')) and running(),'unconfigured_device_posts':missing,'configuration':{k:cfg.get(k) for k in (*FIELDS,'local_post','enabled','peer_urls','standby_ready','single_node')},
            'operation':cfg.get('management_pending') or cfg.get('management_last')}


@router.post('/synchronize')
def synchronize(user:Operator):
    cfg=api().configuration()
    if cfg.get('management_pending'):raise HTTPException(409,'Сначала завершите изменение ролей')
    return api().synchronize(user)


@router.post('/preview')
def preview(value:Selection,user:Operator):
    try:return preflight(api().configuration(),value)
    except (WalletConflict,WalletUnavailable,ValueError) as error:raise HTTPException(409,str(error)) from None


@router.post('/change',status_code=202)
def change(value:Change,user:Operator,credentials:Annotated[HTTPAuthorizationCredentials,Depends(bearer)]):
    fresh(credentials);a=api()
    if not worker_lock.acquire(blocking=False):raise HTTPException(409,'Изменение уже выполняется')
    try:
        with a.control_lock:
            cfg=a.configuration()
            previous=cfg.get('management_last') or {}
            if previous.get('request_id')==str(value.request_id):
                if previous.get('kind')!=value.kind or previous.get('target_post')!=value.target_post:raise WalletConflict('Квитанция относится к другому действию')
                worker_lock.release();return {'ok':True,'operation':previous}
            if roles(cfg)!=value.expected_authority:raise WalletConflict('Роли изменились после проверки. Проверьте посты заново.')
            plan=preflight(cfg,value)
            job={**value.model_dump(exclude={'request_id','expected_authority'}),'request_id':str(value.request_id),'before':plan['before'],
                 'after':plan['after'],'peer_urls':plan['peer_urls'],'stage':'checking','actor':user['login'],
                 'started_at':datetime.now(UTC).isoformat(),'error':None}
            with a.store_context(cfg):persist(cfg,job,'wallet_role_change_started')
        threading.Thread(target=run_job,args=(job['request_id'],),daemon=True).start()
        return {'ok':True,'operation':job}
    except (WalletConflict,WalletUnavailable,ValueError) as error:
        worker_lock.release();raise HTTPException(409,str(error)) from None
    except Exception:
        worker_lock.release();raise


@router.post('/resume',status_code=202)
def resume(value:Resume,user:Operator,credentials:Annotated[HTTPAuthorizationCredentials,Depends(bearer)]):
    fresh(credentials);cfg=api().configuration();job=cfg.get('management_pending')
    if not job or job.get('request_id')!=str(value.request_id) or job['before']['primary_post']!=cfg['local_post']:
        raise HTTPException(409,'Продолжите операцию на посту, где она началась')
    if not worker_lock.acquire(blocking=False):raise HTTPException(409,'Проверка ещё выполняется')
    try:threading.Thread(target=run_job,args=(job['request_id'],),daemon=True).start()
    except Exception:
        worker_lock.release();raise
    return {'ok':True,'operation':job}


@router.post('/cancel')
def cancel(value:Resume,user:Operator,credentials:Annotated[HTTPAuthorizationCredentials,Depends(bearer)]):
    fresh(credentials);a=api()
    if not worker_lock.acquire(blocking=False):raise HTTPException(409,'Дождитесь завершения текущего этапа')
    try:
        with a.control_lock,distributed():
            cfg=a.configuration();job=cfg.get('management_pending')
            if not job or job.get('request_id')!=str(value.request_id) or job['before']['primary_post']!=cfg['local_post']:
                raise WalletConflict('Операция не найдена на этом посту')
            if job['stage'] not in ('checking','copying') or roles(cfg)!=job['before']:
                raise WalletConflict('Переключение уже началось. Отмена запрещена; продолжите проверку.')
            remote({**cfg,'peer_urls':job['peer_urls']},job['target_post'],'abort',job)
            cfg['management_pending']=None;cfg['management_last']={**job,'stage':'aborted','error':None}
            a.persist_configuration(cfg,user,'wallet_role_change_aborted')
        return {'ok':True}
    except (WalletConflict,WalletUnavailable,ManagementBusy) as error:raise HTTPException(409,str(error)) from None
    finally:worker_lock.release()
