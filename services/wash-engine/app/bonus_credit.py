"""Commit confirmed Click credit before publishing it to the wash runtime."""
from psycopg.types.json import Jsonb
from math import ceil
from .db import db
from .bonus import award,remaining,restore

def accept(runtime,amount,key,raw,bonus_override=None):
    if type(amount) is not int or amount<=0:raise ValueError('Positive payment required')
    bonus=award(amount,runtime.params) if bonus_override is None else bonus_override
    if type(bonus) is not int or bonus<0:raise ValueError('Invalid payment bonus')
    reconcile(runtime)
    runtime._flush_usage_locked(settle_spent=True)
    with db() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
        prior=conn.execute('SELECT wash_session_id,amount_sum,bonus_sum FROM payments WHERE idempotency_key=%s',(key,)).fetchone()
        if prior:
            if int(prior['amount_sum'])!=amount:raise ValueError('Payment amount changed')
            if getattr(runtime,'_click_credit_pending',None)==key:
                row=conn.execute('SELECT final_credit_sum,bonus_remaining_sum,source FROM wash_sessions WHERE id=%s',(prior['wash_session_id'],)).fetchone()
                runtime.active_session_id=prior['wash_session_id'];runtime.active_session_source=row['source']
                runtime.state.update(creditSum=int(row['final_credit_sum']),_creditFloat=float(row['final_credit_sum']),activeSessionId=prior['wash_session_id'])
                restore(runtime,int(row['bonus_remaining_sum']))
                runtime._click_credit_pending=None
            return
    sid=runtime._ensure_session_locked('click')
    total=float(runtime.state.get('_creditFloat',runtime.state['creditSum']))+amount+bonus
    bonus_float=float(runtime.state.get("_bonusFloat",runtime.state.get("bonusSum",0)))+bonus
    bonus_total=int(ceil(bonus_float))
    with db() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
        prior=conn.execute('SELECT id FROM payments WHERE idempotency_key=%s',(key,)).fetchone()
        if prior:return
        conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,bonus_sum,idempotency_key,raw_payload,credited_at) VALUES(%s,'click','credited',%s,%s,%s,%s,now())",(sid,amount,bonus,key,Jsonb({**(raw or {}),'bonus_sum':bonus})))
        conn.execute("UPDATE wash_sessions SET paid_sum=paid_sum+%s,final_credit_sum=%s,bonus_granted_sum=bonus_granted_sum+%s,bonus_remaining_sum=%s,status='running',runtime_seen_at=now() WHERE id=%s",(amount,int(ceil(total)),bonus,bonus_total,sid))
        runtime._click_credit_pending=key
        conn.commit()
    runtime._click_credit_pending=None
    runtime.state.update(creditSum=int(ceil(total)),_creditFloat=total,lastCreditSource='click')
    restore(runtime,bonus_float)
    if not runtime.state.get('activeMode') and not runtime.state.get('armedMode'):runtime.state['phase']='idle'


def reconcile(runtime):
    key=getattr(runtime,'_click_credit_pending',None)
    if not key:return
    with db() as conn:
        row=conn.execute('SELECT s.id,s.final_credit_sum,s.bonus_remaining_sum,s.source FROM payments p JOIN wash_sessions s ON s.id=p.wash_session_id WHERE p.idempotency_key=%s',(key,)).fetchone()
    if row:
        runtime.active_session_id=row['id'];runtime.active_session_source=row['source']
        runtime.state.update(creditSum=int(row['final_credit_sum']),_creditFloat=float(row['final_credit_sum']),activeSessionId=row['id'])
        restore(runtime,int(row['bonus_remaining_sum']))
    runtime._click_credit_pending=None
