"""Durable local transfer adapter. Run only while the runtime lock is held.

Network errors leave a frozen job with stable operation IDs. Never clear money
until a confirmed return, and never energize equipment during a transfer.
"""
from datetime import UTC, datetime
from math import ceil
from uuid import uuid4
from psycopg.types.json import Jsonb
from .db import db
from .bonus import remaining as bonus_remaining
from .wallet_domain import WalletConflict
from .wallet_replication import WalletUnavailable
from . import wallet_client
from .wallet_operation import card_operation

POST_SCHEMA_SQL='''
CREATE TABLE IF NOT EXISTS shared_wallet_post_jobs (
 id TEXT PRIMARY KEY, uid TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('load','return')),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done')),
 payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS shared_wallet_one_pending_job ON shared_wallet_post_jobs((1)) WHERE status='pending';
'''


def pending_job():
    with db() as conn:
        return conn.execute("SELECT * FROM shared_wallet_post_jobs WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()


def assignment():
    with db() as conn:
        row=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='wallet_assignment'").fetchone()
    return row['setting_value'] if row and row['setting_value'] else None


def set_job(job,payload):
    with db() as conn:
        conn.execute('UPDATE shared_wallet_post_jobs SET payload=%s WHERE id=%s',(Jsonb(payload),job['id']));conn.commit()
    job['payload']=payload


def initialize_runtime(runtime):
    runtime.shared_wallet_enabled=wallet_client.enabled()
    if not runtime.shared_wallet_enabled:return
    job=pending_job()
    if job:
        runtime.state.update(walletTransferPending=True,selectedMode='pause',activeMode=None,requestedOutput=None,
                             phase='wallet_transfer_pending',walletTransferUid=job['uid'],walletTransferVip=bool(job['payload'].get('is_vip')))


def funding_since(session_id,cursor,post_no):
    with db() as conn:
        rows=conn.execute("SELECT id,provider,amount_sum,idempotency_key,raw_payload,bonus_sum FROM payments WHERE wash_session_id=%s AND id>%s AND provider IN ('cash','click') AND status='credited' ORDER BY id",
                          (session_id,cursor)).fetchall()
    return [{'id':r['idempotency_key'] if str(r.get('idempotency_key') or '').startswith('nv9:') else (r.get("raw_payload") or {}).get("wallet_receipt_id") or f"post:{post_no}:payment:{r['id']}",
             'source':r['provider'],'amount_sum':int(r['amount_sum']),**({'bonus_sum':int(r['bonus_sum'])} if r.get('bonus_sum') else {}),**({'bonus_domain':r['raw_payload']['bonus_domain']} if (r.get('raw_payload') or {}).get('bonus_domain') else {})} for r in rows]


def pause_millis(runtime):
    if runtime.state.get('_pauseBudgetInitialized'):
        return max(0,int(float(runtime.state.get('_pauseBudgetFloat',0))*1000))
    return int(runtime.params['freePauseSeconds']*1000)


def freeze(runtime):
    from .dry_fog_purge import cancel
    cancel(runtime)
    runtime.state.update(walletTransferPending=True,selectedMode='pause',activeMode=None,requestedOutput=None,
                         phase='wallet_transfer_pending',resumeRequiresTriggerReset=bool(runtime.state.get('totalStopActive')))
    publish = getattr(runtime, '_publish_wallet_pending_locked', None)
    if publish is not None:
        publish()
    # Force an actual OFF acknowledgement even if cached last_output is None.
    runtime.last_output='wallet-off-confirmation'
    runtime._apply_output_sync(None)
    runtime._flush_usage_locked(close=True,settle_spent=True)
    runtime._heartbeat_session_locked()


def protocol_fields(runtime,cfg,card=None,ctx=None):
    """Capture protocol/type in the durable job, never infer it during retries."""
    if not ((ctx or {}).get('wallet_protocol')==2 or ((card or {}).get('state') or {}).get('device_wallet') or getattr(runtime,'device_type','wash')=='dry_fog'):
        return {}
    kind=getattr(runtime,'device_type','wash')
    if (ctx or {}).get('device_type',kind)!=kind:raise WalletConflict('Device type changed during an assigned session')
    return {'wallet_protocol':2,'device_type':kind,'bonus_domain':(ctx or {}).get('bonus_domain','shared' if cfg.get('bonus_mode','shared')=='shared' else kind)}


@card_operation()
def handle_card(runtime,uid,event):
    job=pending_job()
    if job and job['uid']!=uid:
        raise WalletConflict('На посту завершается операция другой карты')
    if not job:
        ctx=assignment()
        if ctx and ctx.get('is_vip'):
            raise WalletConflict('Завершите VIP-допуск перед денежной картой')
        if ctx and runtime.active_session_id and runtime.active_session_id!=ctx['session_id'] and int(runtime.state.get('creditSum') or 0)>0:
            raise WalletConflict('На посту другая денежная сессия: сначала завершите её')
        if ctx and ctx['uid']!=uid:
            raise WalletConflict('Баланс сессии связан с другой картой')
        if runtime.active_session_source=='vip':
            raise WalletConflict('Завершите VIP-сеанс перед использованием денежной карты')
        freeze(runtime)
        cfg=wallet_client.discover_configuration()
        if ctx and not int(runtime.state.get('creditSum') or 0):recover_assignment_for_return(runtime,ctx)
        if int(runtime.state.get('creditSum') or 0)>0 or ctx:
            session_id=runtime._ensure_session_locked('card') if int(runtime.state.get('creditSum') or 0)>0 else ctx['session_id']
            with db() as conn:
                cursor=conn.execute('SELECT COALESCE(max(id),0) AS id FROM payments WHERE wash_session_id=%s',(session_id,)).fetchone()['id']
                cash_cursor=conn.execute('SELECT COALESCE(max(id),0) AS id FROM cash_events WHERE wash_session_id=%s',(session_id,)).fetchone()['id']
            payload={'stage':'bind' if not ctx else 'checkpoint','session_id':session_id,'post_no':cfg['local_post'],
                     'assignment_id':ctx['assignment_id'] if ctx else uuid4().hex,'visit_id':ctx['visit_id'] if ctx else uuid4().hex,
                     'amount_sum':int(runtime.state['creditSum']),'bonus_sum':bonus_remaining(runtime),'pause_millis':pause_millis(runtime) if runtime.state['creditSum'] else 0,
                     'payment_cursor':int(cursor),'cash_cursor':int(cash_cursor),
                     'funding':funding_since(session_id,ctx['payment_cursor'],cfg['local_post']) if ctx else []}
            kind='return'
        else:
            if ctx:
                raise WalletConflict('Есть незавершённая привязка карты: нужна сверка восстановления средств')
            card=wallet_client.inspect(uid)
            if not card or not card['available'] or card['state']['wallet_sum']<=0:
                runtime.state['walletTransferPending']=False
                runtime.state['lastRfidStatus']='card_in_use' if card and (card['state'].get('assignment') or not card['available']) else 'customer_card_seen'
                return
            typed=card['state'].get('device_wallet')
            if typed:
                device=getattr(runtime,'device_type','wash')
                other='wash' if device=='dry_fog' else 'dry_fog'
                available=card['state']['wallet_sum']-typed['wallet_bonus'][other]
                if available<=0:
                    runtime.state.update(walletTransferPending=False,lastRfidStatus='bonus_not_available_for_device')
                    return
            payload={'stage':'reserve','post_no':cfg['local_post'],'assignment_id':uuid4().hex,'visit_id':uuid4().hex}
            kind='load'
        card=wallet_client.inspect(uid) if kind=='return' else card
        payload.update(protocol_fields(runtime,cfg,card,ctx))
        if payload.get('wallet_protocol')==2:
            for receipt in payload.get('funding',[]):receipt.setdefault('bonus_domain',payload['bonus_domain'])
        job_id=uuid4().hex
        with db() as conn:
            conn.execute('INSERT INTO shared_wallet_post_jobs(id,uid,kind,payload) VALUES(%s,%s,%s,%s)',(job_id,uid,kind,Jsonb(payload)));conn.commit()
        job={'id':job_id,'uid':uid,'kind':kind,'payload':payload}
    if job['kind']=='return':
        with db() as conn:
            conn.execute("UPDATE click_payment_intents SET wallet_origin_uid=%s WHERE wallet_origin_session_id=%s AND wallet_origin_uid IS NULL",(uid,job['payload']['session_id']));conn.commit()
    freeze(runtime)
    runtime.state['walletTransferUid']=uid
    resume_job(runtime,job)


def resume_job(runtime,job):
    p=job['payload'];base={'post_no':p['post_no'],'assignment_id':p['assignment_id']}
    if p.get('wallet_protocol')==2:base.update({k:p[k] for k in ('wallet_protocol','device_type','bonus_domain')})
    def remote(step,command):
        return wallet_client.execute(job['id']+':'+step,job['uid'],{**base,**command})['result']
    if job['kind']=='load':
        if p['stage']=='reserve':
            result=remote('reserve',{'action':'reserve_load','visit_id':p['visit_id']})
            p.update(stage='accept',amount_sum=result['balance_sum'],bonus_sum=result.get('bonus_sum',0),visit_id=result['visit_id'],pause_millis=result['pause_millis'])
            set_job(job,p)
        if p['stage']=='accept':
            remote('accept',{'action':'accept_load'})
            apply_load(runtime,job)
    else:
        if p['stage']=='bind':
            result=remote('bind',{'action':'open_post','visit_id':p['visit_id'],'amount_sum':p['amount_sum'],'bonus_sum':p.get('bonus_sum',0),'pause_millis':p['pause_millis']})
            p.update(stage='checkpoint',visit_id=result['visit_id'],pause_millis=min(p['pause_millis'],result['pause_millis']))
            set_job(job,p)
        if p['stage']=='checkpoint':
            remote('checkpoint',{'action':'checkpoint','remaining_sum':p['amount_sum'],'remaining_bonus_sum':p.get('bonus_sum',0),'pause_millis':p['pause_millis'],'funding':p['funding']})
            p['stage']='prepare';set_job(job,p)
        if p['stage']=='prepare':
            remote('prepare',{'action':'prepare_return'});p['stage']='complete';set_job(job,p)
        if p['stage']=='complete':
            remote('complete',{'action':'complete_return'})
            apply_return(runtime,job)


def apply_load(runtime,job):
    p=job['payload'];amount=p['amount_sum'];source='vip' if p.get('is_vip') else 'card';ctx={'is_vip':bool(p.get('is_vip')),'uid':job['uid'],'assignment_id':p['assignment_id'],'visit_id':p['visit_id'],'post_no':p['post_no']}
    if p.get('wallet_protocol')==2:ctx.update({k:p[k] for k in ('wallet_protocol','device_type','bonus_domain')})
    with db() as conn:
        conn.execute("INSERT INTO rfid_cards(uid,card_type,status,enabled,balance_sum) VALUES(%s,%s,'active',true,0) ON CONFLICT DO NOTHING",(job['uid'],'vip' if p.get('is_vip') else 'customer'))
        extra=int(runtime.state.get('creditSum') or 0)
        if extra and runtime.active_session_id:
            session=runtime.active_session_id
            conn.execute("UPDATE wash_sessions SET paid_sum=paid_sum+%s,final_credit_sum=%s,source='mixed',metadata=metadata || %s WHERE id=%s",
                         (amount,amount+extra,Jsonb({'wallet_assignment':ctx,'pause_budget_initialized':True,'free_pause_remaining':p['pause_millis']/1000}),session))
        else:
            session=conn.execute("""INSERT INTO wash_sessions(status,source,initial_credit_sum,paid_sum,final_credit_sum,metadata)
            VALUES('running',%s,%s,%s,%s,%s) RETURNING id""",(source,amount,amount,amount,Jsonb({'wallet_assignment':ctx,'pause_budget_initialized':True,'free_pause_remaining':p['pause_millis']/1000}))).fetchone()['id']
        payment=conn.execute("""INSERT INTO payments(wash_session_id,provider,status,amount_sum,idempotency_key,raw_payload,credited_at)
            VALUES(%s,%s,'credited',%s,%s,%s,now()) RETURNING id""",(session,source,amount,'wallet-load:'+job['id'],Jsonb({'uid':job['uid'],'wallet_operation':job['id']}))).fetchone()['id']
        bonus=int(p.get('bonus_sum',0))+bonus_remaining(runtime)
        conn.execute('UPDATE wash_sessions SET bonus_remaining_sum=%s WHERE id=%s',(bonus,session))
        ctx.update(session_id=session,payment_cursor=0 if extra else int(payment))
        conn.execute("INSERT INTO app_settings(setting_key,setting_value,updated_at) VALUES('wallet_assignment',%s,now()) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()",(Jsonb(ctx),))
        conn.execute("INSERT INTO rfid_card_ledger(card_uid,wash_session_id,direction,reason,amount_sum,balance_after_sum,raw_payload) VALUES(%s,%s,%s,%s,%s,0,%s)",
                     (job['uid'],session,'grant' if p.get('is_vip') else 'debit','vip_grant' if p.get('is_vip') else 'use_balance',amount,Jsonb({'operation':job['id']})))
        if p.get('is_vip'):
            conn.execute("UPDATE rfid_card_ledger SET duration_seconds=%s WHERE card_uid=%s AND wash_session_id=%s AND reason='vip_grant'",(0 if p.get('continued') else p['profile']['grant_seconds'],job['uid'],session))
        conn.execute("UPDATE shared_wallet_post_jobs SET status='done',completed_at=now() WHERE id=%s",(job['id'],));conn.commit()
    runtime.state.update(bonusSum=bonus,_bonusFloat=float(bonus))
    runtime.active_session_id=session;runtime.active_session_source=source;runtime.active_session_card_uid=job['uid'];runtime.active_session_initial_credit=amount+extra
    runtime.state.update(creditSum=amount+extra,_creditFloat=float(amount+extra),activeSessionId=session,activeSessionCardUid=job['uid'],
                         _pauseBudgetInitialized=True,_pauseBudgetFloat=p['pause_millis']/1000,freePauseRemaining=ceil(p['pause_millis']/1000),
                         walletTransferPending=False,walletTransferVip=False,walletCashHeld=0,walletLastError=None,walletLastAmount=amount,lastCreditSource=source,lastRfidStatus='vip_granted' if p.get('is_vip') else 'customer_balance_used',
                         phase='idle',armedMode=None,activeMode=None,requestedOutput=None)


def apply_return(runtime,job):
    p=job['payload'];amount=p['amount_sum'];session=p['session_id']
    with db() as conn:
        # Credits received while the transfer was pending stay on this post in
        # a NEW cash session. They are not erased with the frozen return amount.
        extras=conn.execute("SELECT id,amount_sum,bonus_sum FROM payments WHERE wash_session_id=%s AND id>%s AND status='credited' AND provider IN ('cash','click') ORDER BY id",
                            (session,p['payment_cursor'])).fetchall()
        extra_bonus=sum(int(r.get('bonus_sum') or 0) for r in extras)
        extra_money=sum(int(r['amount_sum']) for r in extras)
        extra=extra_money+extra_bonus
        conn.execute("INSERT INTO rfid_cards(uid,card_type,status,enabled,balance_sum) VALUES(%s,%s,'active',true,0) ON CONFLICT DO NOTHING",(job['uid'],'vip' if p.get('is_vip') else 'customer'))
        conn.execute("UPDATE wash_sessions SET status='ended',finished_at=now(),ended_at=now(),final_credit_sum=%s,paid_sum=GREATEST(0,paid_sum-%s),close_reason='saved_to_shared_wallet',metadata=metadata || %s WHERE id=%s",
                     (amount if p.get('is_vip') else 0,extra_money,Jsonb({'wallet_uid':job['uid'],'wallet_return_operation':job['id'],**({'device_wallet_origin':{k:p[k] for k in ('wallet_protocol','device_type','bonus_domain')}} if p.get('wallet_protocol')==2 else {})}),session))
        conn.execute('UPDATE wash_sessions SET bonus_remaining_sum=0 WHERE id=%s',(session,))
        new_session=None
        if extra:
            new_session=conn.execute("INSERT INTO wash_sessions(status,source,initial_credit_sum,paid_sum,final_credit_sum,metadata) VALUES('running','cash',0,%s,%s,%s) RETURNING id",
                                     (extra_money,extra,Jsonb({'created_by':'wallet-transfer-credit-carry'}))).fetchone()['id']
            conn.execute('UPDATE wash_sessions SET bonus_granted_sum=%s,bonus_remaining_sum=%s WHERE id=%s',(extra_bonus,extra_bonus,new_session))
            conn.execute('UPDATE wash_sessions SET bonus_granted_sum=GREATEST(0,bonus_granted_sum-%s) WHERE id=%s',(extra_bonus,session))
            conn.execute('UPDATE payments SET wash_session_id=%s WHERE id=ANY(%s)',(new_session,[r['id'] for r in extras]))
            conn.execute('UPDATE cash_events SET wash_session_id=%s WHERE wash_session_id=%s AND id>%s',(new_session,session,p['cash_cursor']))
        conn.execute("INSERT INTO rfid_card_ledger(card_uid,wash_session_id,direction,reason,amount_sum,balance_after_sum,raw_payload) VALUES(%s,%s,%s,%s,%s,0,%s)",
                     (job['uid'],session,'reversal' if p.get('is_vip') else 'credit','payment_reversal' if p.get('is_vip') else 'save_remaining',0 if p.get('is_vip') else amount,Jsonb({'operation':job['id'],'vip_remaining_value':amount if p.get('is_vip') else None})))
        conn.execute("UPDATE recovery_credits SET status='cancelled',metadata=metadata || %s WHERE wash_session_id=%s AND status='unclaimed'",(Jsonb({'wallet_return_operation':job['id']}),session))
        conn.execute("DELETE FROM app_settings WHERE setting_key='wallet_assignment'")
        conn.execute("UPDATE click_payment_intents SET wallet_origin_uid=%s WHERE wallet_origin_session_id=%s AND wallet_origin_uid IS NULL",(job['uid'],session))
        conn.execute("UPDATE shared_wallet_post_jobs SET status='done',completed_at=now() WHERE id=%s",(job['id'],));conn.commit()
    runtime.active_session_id=new_session;runtime.active_session_source='cash' if extra else 'unknown';runtime.active_session_card_uid=None
    runtime.active_session_initial_credit=0;runtime.ledger_spent_carry=0;runtime.active_usage_id=None;runtime.active_usage_mode=None
    runtime.state.update(bonusSum=extra_bonus,_bonusFloat=float(extra_bonus))
    runtime.state.update(creditSum=extra,_creditFloat=float(extra),activeSessionId=new_session,activeSessionCardUid=None,
                         walletTransferPending=False,walletTransferVip=False,walletCashHeld=0,walletLastError=None,walletLastAmount=amount,_pauseBudgetInitialized=False,_pauseBudgetFloat=0,freePauseRemaining=0,
                         armedMode=None,activeMode=None,requestedOutput=None,selectedMode='pause',phase='idle' if extra else 'no_credit',
                         lastRfidStatus='customer_balance_saved')


def recover_assignment_for_return(runtime,ctx):
    """The same card may return its durable unclaimed recovery credit.

    No new income/payment is created. Reopen its existing session with outputs
    OFF; confirmed return removes the corresponding local recovery claim.
    """
    with db() as conn:
        row=conn.execute("SELECT r.id,r.amount_sum,s.metadata FROM recovery_credits r JOIN wash_sessions s ON s.id=r.wash_session_id WHERE r.wash_session_id=%s AND r.status='unclaimed' FOR UPDATE OF r,s",(ctx['session_id'],)).fetchone()
        if not row or int(row['amount_sum'])<=0:return
        amount=int(row['amount_sum']);metadata=row['metadata'] or {}
        conn.execute("UPDATE recovery_credits SET status='claimed',claimed_at=now() WHERE id=%s",(row['id'],))
        conn.execute("UPDATE wash_sessions SET status='running',ended_at=NULL,finished_at=NULL,final_credit_sum=%s,runtime_seen_at=now(),close_reason='' WHERE id=%s",(amount,ctx['session_id']))
        conn.commit()
    remaining=max(0,float(metadata.get('free_pause_remaining') or 0))
    with db() as conn:
        bonus=conn.execute('SELECT bonus_remaining_sum FROM wash_sessions WHERE id=%s',(ctx['session_id'],)).fetchone()['bonus_remaining_sum']
    runtime.state.update(bonusSum=bonus,_bonusFloat=float(bonus))
    runtime.active_session_id=ctx['session_id'];runtime.active_session_card_uid=ctx['uid'];runtime.active_session_source='card'
    runtime.state.update(creditSum=amount,_creditFloat=float(amount),activeSessionId=ctx['session_id'],activeSessionCardUid=ctx['uid'],
                         _pauseBudgetInitialized=True,_pauseBudgetFloat=remaining,freePauseRemaining=ceil(remaining),
                         selectedMode='pause',armedMode=None,activeMode=None,requestedOutput=None)
