"""Offline reset worker. Run only after engine, Telegram and I/O are stopped.

Never removes host identity, credentials or the durable bill-input cursor.
"""
import os
import sys
from psycopg import sql
from psycopg.types.json import Jsonb
from .db import db, open_pool, close_pool

SETTINGS_KEYS = ('wash_parameters', 'dry_fog_parameters', 'kiosk_settings')


def check_ready(conn, mode):
    if mode not in ('settings', 'full'):
        raise ValueError('Unknown reset mode')
    changing=conn.execute("SELECT 1 FROM app_settings WHERE setting_key='shared_wallet' AND jsonb_typeof(setting_value->'management_pending')='object'").fetchone()
    if changing:
        raise RuntimeError('Сначала завершите или отмените изменение ролей постов')
    # The live API checks idle first; repeat against durable data after stopping
    # all writers. Never erase a customer who arrived while the job was queued.
    busy = conn.execute("SELECT 1 FROM wash_sessions WHERE status='running' AND (final_credit_sum>0 OR source='vip') LIMIT 1").fetchone()
    pending = conn.execute("SELECT 1 FROM shared_wallet_post_jobs WHERE status='pending' LIMIT 1").fetchone()
    if busy or pending:
        raise RuntimeError('Customer credit or an unfinished card operation exists')
    if mode == 'full' and conn.execute("SELECT 1 FROM click_payment_intents WHERE status IN ('local_pending','pending','prepared','paid') LIMIT 1").fetchone():
        raise RuntimeError('Settle or cancel outstanding Click payments before resetting')


def reset(conn, mode):
    check_ready(conn, mode)
    stream, total = os.environ.get('RESET_NV9_STREAM'), os.environ.get('RESET_NV9_TOTAL')
    if stream is not None:
        row = conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=%s', ('nv9_cursor:' + stream,)).fetchone()
        if int((row or {}).get('setting_value', {}).get('total', 0)) != int(total):
            raise RuntimeError('Unprocessed bill pulses exist; reset refused')
    if mode == 'settings':
        conn.execute('DELETE FROM app_settings WHERE setting_key = ANY(%s)', (list(SETTINGS_KEYS),))
    else:
        # One transaction: retain the monotonic stream offset without dangling
        # session/receipt references. The helper journal itself is NOT reset.
        cursors = conn.execute("SELECT setting_key,setting_value FROM app_settings WHERE setting_key LIKE 'nv9_cursor:%'").fetchall()
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename NOT IN ('auth_users','app_settings') ORDER BY tablename").fetchall()
        if tables:
            conn.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY').format(sql.SQL(',').join(sql.Identifier(r['tablename']) for r in tables)))
        conn.execute('DELETE FROM app_settings')
        for row in cursors:
            conn.execute('INSERT INTO app_settings(setting_key,setting_value) VALUES(%s,%s)',
                         (row['setting_key'], Jsonb({'total': int(row['setting_value']['total'])})))
        conn.execute('UPDATE auth_users SET auth_version=auth_version+1,updated_at=now()')
    conn.execute("INSERT INTO system_events(level,event_type,source,message,context) VALUES('warning','factory_reset','system-maintenance',%s,%s)",
                 (mode, Jsonb({'mode': mode, 'accounts_preserved': True})))
    conn.commit()


if __name__ == '__main__':
    open_pool()
    try:
        with db() as connection:
            reset(connection, sys.argv[1])
    finally:
        close_pool()
