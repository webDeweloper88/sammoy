"""Calendar-based retention. Runs outside the wash lock; never edits card balances."""
import asyncio
from contextlib import suppress
from datetime import datetime, UTC
import logging
import time
import threading
from psycopg.types.json import Jsonb
from .db import db

BATCH_SIZE = 1000
MAX_BATCHES = 10
EVENT_MONTHS = 1
FINANCIAL_MONTHS = 12
log = logging.getLogger(__name__)
_task = None
_stopping = threading.Event()

# Unclaimed credit pins the entire session and its financial trail indefinitely.
CLOSED = """s.status IN ('ended','closed','cancelled','error')
    AND COALESCE(s.ended_at,s.finished_at,s.started_at) < now() - interval '12 months'
    AND NOT EXISTS (SELECT 1 FROM app_settings a WHERE a.setting_key='wallet_assignment' AND a.setting_value->>'session_id'=s.id::text)
    AND NOT EXISTS (SELECT 1 FROM shared_wallet_post_jobs j WHERE j.status='pending' AND j.payload->>'session_id'=s.id::text)
    AND NOT EXISTS (SELECT 1 FROM recovery_credits r WHERE r.wash_session_id=s.id AND r.status='unclaimed')
    AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.wash_session_id=s.id
        AND (p.status='pending' OR (p.provider='click' AND p.status='paid' AND p.credited_at IS NULL)))"""
SAFE_SESSION = f"(t.wash_session_id IS NULL OR EXISTS (SELECT 1 FROM wash_sessions s WHERE s.id=t.wash_session_id AND {CLOSED}))"
RULES = [
    ('auth_revoked_tokens', 'jti', 't.expires_at < now()'),
    ('auth_login_attempts', 'login', "t.updated_at < now() - interval '1 month' AND (t.locked_until IS NULL OR t.locked_until < now())"),
    ('system_events', 'id', "t.created_at < now() - interval '1 month'"),
    ('settings_history', 'id', "t.created_at < now() - interval '1 month'"),
    ('payments', 'id', f"t.created_at < now() - interval '12 months' AND t.status<>'pending' AND NOT (t.provider='click' AND t.status='paid' AND t.credited_at IS NULL) AND {SAFE_SESSION}"),
    ('cash_events', 'id', f"t.created_at < now() - interval '12 months' AND {SAFE_SESSION}"),
    ('rfid_card_ledger', 'id', f"t.created_at < now() - interval '12 months' AND {SAFE_SESSION}"),
    ('mode_usage', 'id', f"t.ended_at < now() - interval '12 months' AND {SAFE_SESSION}"),
    ('click_payment_intents', 'id', "GREATEST(t.created_at,t.updated_at,COALESCE(t.credited_at,t.created_at),COALESCE(t.cancelled_at,t.created_at)) < now() - interval '12 months' AND t.status IN ('credited','cancelled','expired','error')"),
    ('wash_sessions', 'id', CLOSED.replace('s.', 't.') + """
        AND NOT EXISTS (SELECT 1 FROM payments x WHERE x.wash_session_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM cash_events x WHERE x.wash_session_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM rfid_card_ledger x WHERE x.wash_session_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM mode_usage x WHERE x.wash_session_id=t.id)"""),
]

def save_status(value):
    with db() as conn:
        conn.execute("SET LOCAL lock_timeout='250ms'")
        conn.execute("SET LOCAL statement_timeout='2s'")
        conn.execute("INSERT INTO app_settings(setting_key,setting_value,updated_at) VALUES('retention_status',%s,now()) ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=now()",(Jsonb(value),))
        conn.commit()

def cleanup():
    result={'last_run_at':datetime.now(UTC).isoformat(),'ok':False,'deleted':{},'more_pending':False}
    started=time.monotonic()
    try:
        for table,key,condition in RULES:
            result['deleted'][table]=0
            for _ in range(MAX_BATCHES):
                if _stopping.is_set() or time.monotonic()-started>20:
                    result['more_pending']=True
                    break
                with db() as conn:
                    conn.execute("SET LOCAL lock_timeout = '250ms'")
                    conn.execute("SET LOCAL statement_timeout = '2s'")
                    if not conn.execute('SELECT pg_try_advisory_xact_lock(72432201) AS acquired').fetchone()['acquired']:
                        result['more_pending']=True
                        break
                    # Table/key/condition are constants above, never request input.
                    count=conn.execute(f"DELETE FROM {table} WHERE {key} IN (SELECT t.{key} FROM {table} t WHERE {condition} ORDER BY t.{key} LIMIT %s FOR UPDATE OF t SKIP LOCKED)",(BATCH_SIZE,)).rowcount
                    conn.commit()
                result['deleted'][table]+=count
                if count<BATCH_SIZE:break
            else:result['more_pending']=True
        result['ok']=True
    except Exception as exc:
        result['error']=type(exc).__name__
        log.exception('Retention cleanup failed; remaining data was preserved')
    save_status(result)
    return result

async def start():
    global _task
    _stopping.clear()
    async def loop():
        while True:
            worker=asyncio.create_task(asyncio.to_thread(cleanup))
            try:await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Complete the current short batch before the DB pool closes.
                with suppress(Exception):await worker
                raise
            except Exception:log.exception('Retention status could not be saved')
            await asyncio.sleep(3600)
    _task=asyncio.create_task(loop())

async def stop():
    _stopping.set()
    if _task:
        _task.cancel()
        with suppress(asyncio.CancelledError):await _task
