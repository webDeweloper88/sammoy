"""Freeze local VIP sources; replicated imports require explicit Owner actions."""
from datetime import UTC,datetime,timedelta
from uuid import uuid4,UUID
import re
from psycopg.types.json import Jsonb
from .db import db
from .wallet_domain import WalletConflict,WalletPolicy
from .wallet_replication import WalletUnavailable
from .wallet_api import configuration,authority,rpc,control_lock,store_context,coordinator
from .wallet_registry import PROFILES_UID,profile_value,owner_operation

GATE_UID='@vip-migration'
VIP_IMPORT_SCHEMA_SQL='''
CREATE TABLE IF NOT EXISTS shared_wallet_vip_imports(
 id UUID PRIMARY KEY,uid TEXT NOT NULL UNIQUE REFERENCES rfid_cards(uid),
 source_snapshot JSONB NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','done')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),completed_at TIMESTAMPTZ);
'''
PROFILE_KEYS=('code','name','enabled','grant_seconds','max_uses_per_day','owner_notes')

def source_status():
    cfg=configuration()
    with db() as c:
        pending=int(c.execute("SELECT count(*) n FROM shared_wallet_vip_imports WHERE status='pending'").fetchone()['n'])
        legacy=int(c.execute("SELECT count(*) n FROM rfid_cards WHERE card_type='vip'").fetchone()['n']) if not cfg['enabled'] else 0
    return {'ok':True,'vip_import_protocol':1,'site_id':cfg['site_id'],'local_post':cfg['local_post'],'generation':cfg['generation'],
            'enabled':cfg['enabled'],'pending':pending,'legacy':legacy}

def snapshot(c,card,cfg,minutes):
    profile=c.execute('SELECT * FROM vip_profiles WHERE id=%s',(card['vip_profile_id'],)).fetchone()
    if not profile:raise WalletConflict(f"VIP {card['uid']}: сначала укажите локальный профиль")
    if card['balance_sum'] or card.get('bonus_sum'):raise WalletConflict('VIP содержит денежный остаток: нужна сверка')
    active=c.execute("SELECT 1 FROM wash_sessions WHERE card_uid=%s AND status IN ('running','open','started') LIMIT 1",(card['uid'],)).fetchone()
    if active:raise WalletConflict('Завершите активный локальный VIP-сеанс перед установкой')
    today=c.execute("SELECT (now() AT TIME ZONE 'Asia/Tashkent')::date AS day").fetchone()['day']
    used=int(c.execute("SELECT count(*) n FROM rfid_card_ledger WHERE card_uid=%s AND reason='vip_grant' AND raw_payload->>'operation' IS NULL AND (created_at AT TIME ZONE 'Asia/Tashkent')::date=%s",(card['uid'],today)).fetchone()['n'])
    latest=c.execute("SELECT * FROM wash_sessions WHERE card_uid=%s AND source IN ('vip','mixed') ORDER BY started_at DESC,id DESC LIMIT 1",(card['uid'],)).fetchone()
    recoveries=c.execute("SELECT r.* FROM recovery_credits r JOIN wash_sessions s ON s.id=r.wash_session_id WHERE s.card_uid=%s AND s.source='vip' AND r.status='unclaimed' ORDER BY r.id",(card['uid'],)).fetchall()
    if len(recoveries)>1:raise WalletConflict('Несколько невосстановленных локальных VIP-сеансов: нужна сверка')
    visit=None
    if latest:
        # Legacy VIP grants were recorded as virtual water-tariff credits in
        # paid_sum. Prove their origin from BOTH payment and grant ledgers;
        # never treat an unexplained paid_sum as a safe virtual allowance.
        real_payment=c.execute("SELECT 1 FROM payments WHERE wash_session_id=%s AND provider!='vip' AND status IN ('pending','paid','credited') AND amount_sum>0 LIMIT 1",(latest['id'],)).fetchone()
        cash=c.execute('SELECT 1 FROM cash_events WHERE wash_session_id=%s LIMIT 1',(latest['id'],)).fetchone()
        card_money=c.execute("SELECT 1 FROM rfid_card_ledger WHERE wash_session_id=%s AND reason!='vip_grant' AND amount_sum>0 LIMIT 1",(latest['id'],)).fetchone()
        if latest['source']=='mixed' or real_payment or cash or card_money or latest.get('bonus_granted_sum'):
            raise WalletConflict('VIP смешан с денежной оплатой: сначала сверите остаток сеанса')
        if latest['paid_sum']:
            virtual=c.execute("SELECT COALESCE(sum(amount_sum),0) amount FROM payments WHERE wash_session_id=%s AND provider='vip' AND status IN ('paid','credited') AND raw_payload->>'conversion'='water_tariff'",(latest['id'],)).fetchone()['amount']
            granted=c.execute("SELECT COALESCE(sum(amount_sum),0) amount FROM rfid_card_ledger WHERE wash_session_id=%s AND card_uid=%s AND direction='grant' AND reason='vip_grant'",(latest['id'],card['uid'])).fetchone()['amount']
            if virtual!=latest['paid_sum'] or granted!=latest['paid_sum']:
                raise WalletConflict('VIP: источник виртуального лимита не подтверждён, нужна сверка')
        end=latest['ended_at'] or latest['finished_at'] or latest['runtime_seen_at'] or latest['started_at']
        meta=latest['metadata'] or {}
        recovery=recoveries[0] if recoveries else None
        if recovery and recovery['wash_session_id']!=latest['id']:raise WalletConflict('VIP-остаток относится к прежнему сеансу: нужна сверка')
        remaining=int(recovery['amount_sum']) if recovery else 0
        pause=min(86400000,max(0,int(float(meta.get('free_pause_remaining') or 0)*1000))) if remaining else 0
        visit={'remaining_sum':remaining,'pause_millis':pause,'expires_at':(end+timedelta(minutes=minutes)).isoformat(),
               'timeout_minutes':minutes,'water_reference':{'amount_sum':0,'duration_seconds':0}}
    expiry=card.get('expires_at')
    return {'uid':card['uid'],'enabled':card['enabled'],'status':'expired' if expiry and expiry<=datetime.now(UTC) else card['status'],
            'expires_at':expiry.isoformat() if expiry else None,'display_name':card['display_name'],
            'profile':{k:profile[k] for k in PROFILE_KEYS},'daily_uses':{today.isoformat():used} if used else {},
            'visit':visit,'recovery_id':recoveries[0]['id'] if recoveries else None,'site_id':cfg['site_id'],'post_no':cfg['local_post']}

def stage_all(c,cfg,user):
    minutes=cfg['visit_timeout_minutes']
    for card in c.execute("SELECT * FROM rfid_cards WHERE card_type='vip' ORDER BY uid FOR UPDATE").fetchall():
        if not re.fullmatch('[0-9A-F]{4,64}',card['uid']):raise WalletConflict('VIP UID должен соответствовать реальной NFC-карте')
        prior=c.execute('SELECT * FROM shared_wallet_vip_imports WHERE uid=%s',(card['uid'],)).fetchone()
        if prior:
            if prior['source_snapshot']['site_id']!=cfg['site_id'] or prior['source_snapshot']['post_no']!=cfg['local_post']:raise WalletConflict('Изменена идентичность VIP-источника')
            if card['enabled']:raise WalletConflict('Замороженный VIP-источник снова включён: нужна сверка')
            if prior['status']=='done':raise WalletConflict('VIP уже переносился: восстановите конфигурацию общего кошелька')
        else:
            source=snapshot(c,card,cfg,minutes)
            c.execute("INSERT INTO shared_wallet_vip_imports(id,uid,source_snapshot,status) VALUES(%s,%s,%s,'pending')",(uuid4(),card['uid'],Jsonb(source)))
        c.execute('UPDATE rfid_cards SET enabled=false,updated_at=now() WHERE uid=%s',(card['uid'],))

def preview(after='',limit=30):
    cfg=configuration()
    with db() as c:
        rows=c.execute("SELECT uid,status,source_snapshot FROM shared_wallet_vip_imports WHERE uid>%s ORDER BY uid LIMIT %s",(after,limit+1)).fetchall()
        cards=[{'uid':r['uid'],'import_status':r['status'],**{k:r['source_snapshot'][k] for k in ('display_name','profile','enabled','status','daily_uses','visit')}} for r in rows[:limit]]
        unstaged=int(c.execute("SELECT count(*) n FROM rfid_cards c WHERE card_type='vip' AND NOT EXISTS(SELECT 1 FROM shared_wallet_vip_imports j WHERE j.uid=c.uid)").fetchone()['n']) if not cfg['enabled'] else 0
    return {'ok':True,'enabled':cfg['enabled'],'post_no':cfg['local_post'],'cards':cards,'unstaged':unstaged,
            'next_after':rows[limit-1]['uid'] if len(rows)>limit else None}

def lock_gate(store,cfg,actor):
    row=store.inspect(GATE_UID)
    if row and not row['state']['service_configuration'].get('complete',False) and not row['pending_operation']:return
    owner_operation(store,cfg,GATE_UID,{'action':'configure_service','value':{'complete':False},'actor':actor})

def require_nodes(cfg):
    if not cfg['single_node']:
        status=rpc(cfg,cfg['standby_post'],'status',{})
        if status.get('vip_import_protocol')!=1 or status.get('local_post')!=cfg['standby_post'] or status.get('generation')!=cfg['generation']:
            raise WalletUnavailable('Обновите главный и резервный посты для переноса VIP')

def import_on_primary(store,cfg,payload,sender):
    source=payload.get('snapshot');uid=payload.get('uid');operation=payload.get('operation_id')
    if not isinstance(source,dict) or not isinstance(uid,str) or not re.fullmatch('[0-9A-F]{4,64}',uid) or source.get('uid')!=uid or source.get('post_no')!=sender or source.get('site_id')!=cfg['site_id']:
        raise WalletConflict('Invalid VIP migration identity')
    try:
        if str(UUID(operation.removeprefix('vip-job:')))!=operation.removeprefix('vip-job:') or not operation.startswith('vip-job:'):raise ValueError()
    except (ValueError,TypeError,AttributeError):raise WalletConflict('Invalid VIP operation ID') from None
    require_nodes(cfg);lock_gate(store,cfg,f'post-{sender}')
    existing=store._operation(operation)
    if existing:
        if existing['command'].get('snapshot')!=source:raise WalletConflict('VIP source changed after prepare')
        command=existing['command']
    else:
        profiles=profile_value(store);incoming=source.get('profile',{})
        profile=next((p for p in profiles if p['code']==incoming.get('code')),None)
        if profile:
            if any(profile.get(k)!=incoming.get(k) for k in ('enabled','grant_seconds','max_uses_per_day')):
                raise WalletConflict('Локальный и общий VIP-профили расходятся: сверите тариф и дневной лимит')
        else:
            from .schema import VipProfileRequest
            incoming=VipProfileRequest(**incoming).model_dump();incoming['code']=incoming['code'].strip().upper();incoming['name']=incoming['name'].strip()
            if not incoming['code'] or not incoming['name']:raise WalletConflict('Invalid source VIP profile')
            profile={**incoming,'id':max([p['id'] for p in profiles]+[0])+1}
            owner_operation(store,cfg,PROFILES_UID,{'action':'configure_service','value':{'profiles':profiles+[profile]},'actor':f'post-{sender}'})
        command={'action':'import_vip','post_no':sender,'receipt_id':f'vip-import:post:{sender}:{uid}','profile':profile,'snapshot':source}
    return coordinator(store,cfg).execute(operation,uid,command,WalletPolicy(cfg['visit_timeout_minutes']))

def transfer(uid,confirmation,user):
    if confirmation!=f'IMPORT VIP {uid}':raise WalletConflict('Подтвердите UID переносимой VIP-карты')
    cfg=configuration();authority(cfg)
    with db() as c:
        job=c.execute('SELECT * FROM shared_wallet_vip_imports WHERE uid=%s',(uid,)).fetchone()
    if not job:raise WalletConflict('Сначала сохраните локальные VIP при установке общего кошелька')
    if job['status']=='done':return {'ok':True,'already_imported':True}
    source=job['source_snapshot']
    from .wallet_client import discover_configuration
    cfg=discover_configuration()
    if source['site_id']!=cfg['site_id'] or source['post_no']!=cfg['local_post']:raise WalletConflict('Изменена идентичность источника VIP')
    rpc(cfg,cfg['primary_post'],'import-vip',{'uid':uid,'snapshot':source,'operation_id':'vip-job:'+str(job['id'])})
    with db() as c:
        card=c.execute('SELECT card_type,enabled FROM rfid_cards WHERE uid=%s FOR UPDATE',(uid,)).fetchone()
        if not card or card['card_type']!='vip' or card['enabled']:raise WalletConflict('Локальный VIP-источник изменён: нужна сверка')
        recovery=source.get('recovery_id')
        if recovery:
            c.execute("UPDATE recovery_credits SET status='cancelled',metadata=metadata||%s WHERE id=%s AND status='unclaimed'",(Jsonb({'vip_migration_operation':'vip-job:'+str(job['id'])}),recovery))
        c.execute("UPDATE shared_wallet_vip_imports SET status='done',completed_at=now() WHERE uid=%s",(uid,));c.commit()
    return {'ok':True}

def gate_locked(store):
    row=store.inspect(GATE_UID)
    return bool(row and (row['pending_operation'] or not row['state']['service_configuration'].get('complete',False)))

def finish(user,confirmation):
    cfg=configuration();authority(cfg).require_primary()
    if confirmation!=f"COMPLETE VIP MIGRATION SITE {cfg['site_id']}":raise WalletConflict('Подтвердите завершение переноса VIP всей мойки')
    require_nodes(cfg)
    nodes=[]
    for key in sorted(cfg['peer_urls'],key=int):
        post=int(key);proof=source_status() if post==cfg['local_post'] else rpc(cfg,post,'vip-import-status',{})
        if proof.get('vip_import_protocol')!=1 or proof.get('local_post')!=post or proof.get('site_id')!=cfg['site_id'] or not proof.get('enabled') or proof.get('generation')!=cfg['generation'] or proof.get('pending') or proof.get('legacy'):
            raise WalletConflict(f'Пост {post}: перенос VIP не завершён или требуется обновление')
        nodes.append(post)
    with control_lock,store_context(cfg) as store:
        current=configuration()
        if any(current.get(k)!=cfg.get(k) for k in ('enabled','site_id','primary_post','standby_post','generation','peer_urls')):raise WalletConflict('Состав постов изменился: повторите проверку')
        owner_operation(store,cfg,GATE_UID,{'action':'configure_service','value':{'complete':True,'checked_posts':nodes},'actor':user['login']})
    return {'ok':True,'checked_posts':nodes}

def guard_grant(store,cfg):
    gate=store.inspect(GATE_UID)
    if gate:
        if gate_locked(store):raise WalletConflict('Сначала завершите перенос VIP всех постов в Owner')
        return
    # Before the first explicit completion, prove known sources have no legacy
    # cards. After completion, healthy ordinary posts are not a VIP dependency.
    for key in cfg['peer_urls']:
        post=int(key);proof=source_status() if post==cfg['local_post'] else rpc(cfg,post,'vip-import-status',{})
        if proof.get('vip_import_protocol')!=1 or proof.get('local_post')!=post or proof.get('site_id')!=cfg['site_id'] or proof.get('generation')!=cfg['generation'] or proof.get('pending') or proof.get('legacy') or not proof.get('enabled'):
            raise WalletConflict(f'Пост {post}: сначала завершите перенос VIP')
