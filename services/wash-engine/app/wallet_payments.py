"""Bind confirmed Click credits to the original paid session or its wallet."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from .db import db
from . import wallet_client

PAYMENT_SCHEMA_SQL='''
ALTER TABLE click_payment_intents ADD COLUMN IF NOT EXISTS wallet_origin_session_id BIGINT;
ALTER TABLE click_payment_intents ADD COLUMN IF NOT EXISTS wallet_origin_uid TEXT;
ALTER TABLE click_payment_intents ADD COLUMN IF NOT EXISTS wallet_credit_destination TEXT;
'''


def bind_new_intent(runtime):
    if not runtime.shared_wallet_enabled:return None,None
    with runtime.lock:
        if runtime.active_session_source=='vip':
            raise ValueError('Завершите VIP-сеанс перед денежной оплатой')
        if runtime.state.get('walletTransferPending'):
            raise ValueError('Завершите операцию карты перед созданием новой оплаты')
        runtime.state['onlinePaymentPending']=True
        import time
        runtime.state['_onlineIntentStarted']=time.monotonic()
        session=runtime._ensure_session_locked('click')
        return session,runtime.active_session_card_uid


def payment_protocol(runtime,card,session_id,cfg):
    if not ((card or {}).get('state') or {}).get('device_wallet'):return {}
    with db() as conn:
        row=conn.execute('SELECT metadata FROM wash_sessions WHERE id=%s',(session_id,)).fetchone()
    meta=(row or {}).get('metadata') or {}
    origin=meta.get('device_wallet_origin') or meta.get('wallet_assignment') or {}
    kind=origin.get('device_type',getattr(runtime,'device_type',cfg.get('device_types',{}).get(str(cfg.get('local_post')),'wash')))
    return {'wallet_protocol':2,'device_type':kind,'bonus_domain':origin.get('bonus_domain','shared' if cfg.get('bonus_mode','shared')=='shared' else kind)}


def credit_confirmed(runtime,row):
    """Return destination; provider status must already be verified by main.py."""
    origin=row.get('wallet_origin_session_id')
    amount=int(row['amount_sum']);bonus=int(row.get('bonus_sum') or 0);gateway=str(row.get('gateway_intent_id') or row['id'])
    key='click:'+gateway
    with runtime.lock:
        if origin and runtime.active_session_id==origin and not runtime.state.get('walletTransferPending') and runtime.active_session_source!='vip':
            runtime.add_credit(amount,'click',idempotency_key=key,raw_payload={'intent_id':str(row['id']),'origin_session_id':origin},bonus_sum=bonus)
            return 'post'
        uid=row.get('wallet_origin_uid')
        if not uid:
            with db() as conn:
                session=conn.execute('SELECT metadata FROM wash_sessions WHERE id=%s',(origin,)).fetchone()
            uid=(session['metadata'] or {}).get('wallet_uid') if session else None
        if uid:
            card=wallet_client.inspect(uid)
            if card and card['state'].get('card_type')!='customer':uid=None
        if uid:
            cfg=wallet_client.discover_configuration()
            wallet_client.execute('click-credit:'+str(row['id']),uid,{'action':'wallet_credit','post_no':cfg['local_post'],
                 'amount_sum':amount,'bonus_sum':bonus,'receipt_id':key,'source':'click',**payment_protocol(runtime,card,origin,cfg)})
            with db() as conn:
                conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,idempotency_key,raw_payload,credited_at) VALUES(%s,'click','credited',%s,%s,%s,now()) ON CONFLICT(idempotency_key) DO NOTHING",
                             (origin,amount,key,Jsonb({'wallet_uid':uid,'destination':'wallet','intent_id':str(row['id']),'bonus_sum':bonus})))
                conn.execute('UPDATE payments SET bonus_sum=%s WHERE idempotency_key=%s',(bonus,key));conn.commit()
            return 'wallet'
        # An anonymous closed session has no proven wallet owner. Preserve the
        # payment for operator recovery, never give it to another customer.
        with db() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
            prior=conn.execute('SELECT id FROM payments WHERE idempotency_key=%s',(key,)).fetchone()
            if not prior:
                recovered=conn.execute("INSERT INTO wash_sessions(status,source,paid_sum,final_credit_sum,ended_at,finished_at,close_reason,metadata) VALUES('ended','click',%s,%s,now(),now(),'late_click_recovery',%s) RETURNING id",
                                       (amount,amount+bonus,Jsonb({'origin_session_id':origin,'intent_id':str(row['id'])}))).fetchone()['id']
                conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,idempotency_key,raw_payload,credited_at) VALUES(%s,'click','credited',%s,%s,%s,now())",
                             (recovered,amount,key,Jsonb({'origin_session_id':origin,'destination':'recovery'})))
                conn.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status,metadata) VALUES(%s,%s,'late_click_payment','unclaimed',%s)",
                             (recovered,amount+bonus,Jsonb({'origin_session_id':origin,'intent_id':str(row['id'])})))
            if not prior:
                conn.execute('UPDATE payments SET bonus_sum=%s WHERE idempotency_key=%s',(bonus,key))
                conn.execute('UPDATE wash_sessions SET bonus_granted_sum=%s,bonus_remaining_sum=%s WHERE id=%s',(bonus,bonus,recovered))
                conn.execute('UPDATE recovery_credits SET bonus_sum=%s WHERE wash_session_id=%s',(bonus,recovered))
            conn.commit()
        return 'recovery'


def waiting_payment(runtime):
    if not runtime.shared_wallet_enabled or not runtime.state.get('onlinePaymentPending') or not runtime.active_session_id:
        return False
    with db() as conn:
        row=conn.execute("SELECT 1 FROM click_payment_intents WHERE wallet_origin_session_id=%s AND status IN ('local_pending','pending','prepared','paid') AND credited_at IS NULL AND created_at>now()-interval '30 minutes' LIMIT 1",
                         (runtime.active_session_id,)).fetchone()
    # The short create-request window precedes INSERT; keep the zero-credit
    # session only while registration is in progress (bounded monotonic timer).
    import time
    waiting=bool(row) or time.monotonic()-runtime.state.get('_onlineIntentStarted',-100)<=10
    if not waiting:runtime.state['onlinePaymentPending']=False
    return waiting


def defer_vip_cash(runtime,amount,source,pulse_count,raw):
    """Physical cash cannot be refused by software after a pulse was received.

    Preserve it as a separate recoverable monetary credit rather than mixing it
    into a virtual VIP grant. Duplicate physical events have a stable ledger key.
    """
    if not runtime.shared_wallet_enabled or (runtime.active_session_source!='vip' and not runtime.state.get('walletTransferVip')):return False
    identity=raw.get('rising_count',raw.get('physical_rising_count'))
    key=f"vip-cash:{runtime.active_session_id}:{source}:{identity}:{raw.get('simulated_pulses',0)}"
    with db() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
        existing=conn.execute('SELECT id FROM payments WHERE idempotency_key=%s',(key,)).fetchone()
        if not existing:
            session=conn.execute("INSERT INTO wash_sessions(status,source,paid_sum,final_credit_sum,ended_at,finished_at,close_reason,metadata) VALUES('ended','cash',%s,%s,now(),now(),'vip_cash_recovery',%s) RETURNING id",
                                 (amount,amount,Jsonb({'vip_session_id':runtime.active_session_id}))).fetchone()['id']
            conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,idempotency_key,raw_payload,credited_at) VALUES(%s,'cash','credited',%s,%s,%s,now())",(session,amount,key,Jsonb(raw)))
            conn.execute('INSERT INTO cash_events(wash_session_id,source_input,pulse_count,amount_sum,sum_per_pulse,raw_payload) VALUES(%s,%s,%s,%s,%s,%s)',
                         (session,source,pulse_count,amount,amount//pulse_count,Jsonb(raw)))
            conn.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status,metadata) VALUES(%s,%s,'cash_during_vip','unclaimed',%s)",
                         (session,amount,Jsonb({'vip_session_id':runtime.active_session_id})))
        conn.commit()
    runtime.state['walletCashHeld']=int(runtime.state.get('walletCashHeld') or 0)+(0 if existing else amount)
    return True


def restore_recovery(recovery_id,uid,actor):
    """Owner-authorized transfer of preserved local money to one bound wallet.

    Persist the target before RPC. An uncertain response must be retried for
    that same card; another target can never receive the same recovery credit.
    """
    from .wallet_domain import WalletConflict
    from .wallet_post import assignment
    if not wallet_client.enabled():raise WalletConflict('Сначала установите общий кошелёк')
    ctx=assignment()
    with db() as conn:
        row=conn.execute('SELECT * FROM recovery_credits WHERE id=%s FOR UPDATE',(recovery_id,)).fetchone()
        if not row:raise WalletConflict('Остаток для восстановления не найден')
        source_session=conn.execute('SELECT source FROM wash_sessions WHERE id=%s',(row['wash_session_id'],)).fetchone()
        if source_session and source_session['source']=='vip':raise WalletConflict('Это VIP-время: переносите VIP-карту, а не денежный остаток')
        meta=dict(row['metadata'] or {})
        if row['status']=='claimed' and meta.get('wallet_target_uid')==uid:return {'ok':True,'already_restored':True}
        if row['status']!='unclaimed':raise WalletConflict('Этот остаток уже обработан')
        if ctx and ctx['session_id']==row['wash_session_id']:
            raise WalletConflict('Остаток связан с активной картой: завершите её операцию на этом посту')
        if meta.get('wallet_target_uid') and meta['wallet_target_uid']!=uid:
            raise WalletConflict('Перевод уже связан с другой картой; повторите его на ту же карту')
        if int(row['amount_sum'])<=0:raise WalletConflict('Нет денежного остатка')
        source='click' if row['reason']=='late_click_payment' else 'cash'
        meta.update(wallet_target_uid=uid,wallet_restore_actor=actor,wallet_restore_source=source)
        conn.execute('UPDATE recovery_credits SET metadata=%s WHERE id=%s',(Jsonb(meta),recovery_id));conn.commit()
    cfg=wallet_client.discover_configuration()
    operation=meta.get("wallet_operation_id") or (f"nv9-recovery:{meta['nv9_stream_id']}:{meta['first_pulse']}:{meta['rising_count']}"
        if meta.get("nv9_stream_id") else meta.get("wallet_recovery_id") or f"post:{cfg['local_post']}:recovery:{recovery_id}")
    wallet_client.execute(operation,uid,{'action':'wallet_credit','post_no':cfg['local_post'],
        'amount_sum':int(row['amount_sum'])-int(row.get('bonus_sum') or 0),'bonus_sum':int(row.get('bonus_sum') or 0),'receipt_id':operation,'source':source,**payment_protocol(None,wallet_client.inspect(uid),row['wash_session_id'],cfg)})
    with db() as conn:
        conn.execute("UPDATE recovery_credits SET status='claimed',claimed_at=now(),metadata=metadata||%s WHERE id=%s AND status='unclaimed'",(Jsonb({'wallet_operation_id':operation}),recovery_id));conn.commit()
    return {'ok':True,'uid':uid,'amount_sum':int(row['amount_sum'])}
