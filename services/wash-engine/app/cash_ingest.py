"""Credit durable NV9 ranges and acknowledge them in one PostgreSQL commit.

Cash with uncertain ownership is held for Owner recovery, never handed to a
new customer or mixed with a virtual VIP grant. No helper acknowledgment RPC:
PostgreSQL owns the processed cursor, helper owns the persistent source total.
"""
from uuid import UUID
from math import ceil
from psycopg.types.json import Jsonb
from .db import db

def capture(runtime,io,*,recover=False):
    stream=io.get('nv9_stream_id')
    if stream is None:return False  # Legacy fixtures/protocol; production checks separately.
    try:
        stream=UUID(stream).hex
        total=io['nv9_pulses']
        if type(total) is not int or total<0:raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError):
        raise RuntimeError('Invalid durable NV9 stream') from None
    if getattr(runtime,'_nv9_confirmed',None)==(stream,total):return True
    key='nv9_cursor:'+stream
    with runtime.lock:
        with db() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
            row=conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=%s FOR UPDATE',(key,)).fetchone()
            previous=int(row['setting_value']['total']) if row else 0
            if total<previous:raise RuntimeError('NV9 journal counter moved backwards')
            delta=total-previous
            if delta or getattr(runtime, "_nv9_pending", None):
                from .dry_fog_purge import cancel
                cancel(runtime)
            pending=getattr(runtime,'_nv9_pending',None)
            if pending and pending[0]==stream and previous>=pending[1] and row:
                accepted=row['setting_value']
                if not accepted.get('held'):
                    session=conn.execute('SELECT final_credit_sum,source,bonus_remaining_sum FROM wash_sessions WHERE id=%s',(accepted['session_id'],)).fetchone()
                    if session:
                        runtime.active_session_id=accepted['session_id']
                        runtime.active_session_source=session['source']
                        runtime.state['activeSessionId']=runtime.active_session_id
                        runtime.state['creditSum']=int(session['final_credit_sum'])
                        runtime.state['_creditFloat']=float(runtime.state['creditSum'])
                        from .bonus import restore
                        restore(runtime,session['bonus_remaining_sum'])
                else:
                    held_session=conn.execute('SELECT final_credit_sum FROM wash_sessions WHERE id=%s',(accepted['session_id'],)).fetchone()
                    if held_session:runtime.state['walletCashHeld']=int(runtime.state.get('walletCashHeld') or 0)+int(held_session['final_credit_sum'])
                runtime._nv9_pending=None
                runtime._nv9_uncertain=False
            if not delta:
                runtime._nv9_confirmed=(stream,total)
                runtime.last_bill_pulses=total
                runtime.state['billPulses']=total
                return True
            price=int(runtime.params['billPulseSum'])
            if price<=0:raise RuntimeError('NV9 pulse price must be positive')
            amount=delta*price
            from .bonus import award, remaining, add, restore
            bonus=award(amount,runtime.params)
            available=amount+bonus
            held=bool(recover or runtime.state.get('licenseLocked') or runtime.active_session_source=='vip'
                      or runtime.state.get('walletTransferPending'))
            payload={'bonus_sum':bonus,'bonus_domain':runtime.params.get('bonusDomain','shared'),'nv9_stream_id':stream,'first_pulse':previous+1,'rising_count':total,'sum_per_pulse':price,
                     'held_reason':'restart_or_io_fault' if recover else ('license_locked' if runtime.state.get('licenseLocked') else ('vip' if runtime.active_session_source=='vip' else 'wallet_transfer_pending')) if held else None}
            receipt=f'nv9:{stream}:{previous+1}:{total}'
            if held:
                sid=conn.execute("INSERT INTO wash_sessions(status,source,paid_sum,final_credit_sum,ended_at,finished_at,close_reason,metadata) VALUES('ended','cash',%s,%s,now(),now(),'nv9_cash_recovery',%s) RETURNING id",
                                 (amount,available,Jsonb(payload))).fetchone()['id']
                credit=None
                conn.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status,metadata) VALUES(%s,%s,'nv9_uncertain_owner','unclaimed',%s)",(sid,available,Jsonb(payload)))
                conn.execute('UPDATE recovery_credits SET bonus_sum=%s WHERE wash_session_id=%s',(bonus,sid))
            else:
                sid=runtime.active_session_id
                credit=float(runtime.state.get('_creditFloat',runtime.state['creditSum']))+available
                if sid is None:
                    sid=conn.execute("INSERT INTO wash_sessions(status,source,paid_sum,final_credit_sum,runtime_seen_at,metadata) VALUES('running','cash',%s,%s,now(),%s) RETURNING id",
                                     (amount,int(ceil(credit)),Jsonb({'created_by':'wash-runtime',**payload}))).fetchone()['id']
                else:
                    conn.execute("UPDATE wash_sessions SET paid_sum=paid_sum+%s,final_credit_sum=%s,status='running',runtime_seen_at=now(),source=CASE WHEN source IN ('cash','unknown') THEN 'cash' ELSE 'mixed' END WHERE id=%s",(amount,int(ceil(credit)),sid))
            conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,idempotency_key,raw_payload,credited_at) VALUES(%s,'cash','credited',%s,%s,%s,now())",(sid,amount,receipt,Jsonb(payload)))
            bonus_remaining=bonus if held else remaining(runtime)+bonus
            conn.execute('UPDATE payments SET bonus_sum=%s WHERE idempotency_key=%s',(bonus,receipt))
            conn.execute('UPDATE wash_sessions SET bonus_granted_sum=bonus_granted_sum+%s,bonus_remaining_sum=%s WHERE id=%s',(bonus,bonus_remaining,sid))
            conn.execute("INSERT INTO cash_events(wash_session_id,source_input,pulse_count,amount_sum,sum_per_pulse,raw_payload) VALUES(%s,'bill_pulse',%s,%s,%s,%s)",(sid,delta,amount,price,Jsonb(payload)))
            conn.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES(%s,%s) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()",(key,Jsonb({'total':total,'receipt_id':receipt,'session_id':sid,'held':held})))
            runtime._nv9_uncertain=True
            runtime._nv9_pending=(stream,total)
            conn.commit()
        if held:
            runtime.state['walletCashHeld']=int(runtime.state.get('walletCashHeld') or 0)+available
        else:
            runtime.active_session_id=sid
            runtime.active_session_source='cash' if runtime.active_session_source in (None,'unknown','cash') else 'mixed'
            runtime.state.update(creditSum=int(ceil(credit)),_creditFloat=credit,lastCreditSource='bill_pulse',activeSessionId=sid)
            add(runtime,bonus)
        runtime._nv9_uncertain=False
        runtime._nv9_pending=None
        runtime._nv9_confirmed=(stream,total)
        runtime.last_bill_pulses=total
        runtime.state['billPulses']=total
    return True
