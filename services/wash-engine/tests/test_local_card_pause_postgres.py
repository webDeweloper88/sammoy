"""Disposable database check; never point this at a production DSN."""
import os, unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.wash_logic import WashRuntime
from app.local_card_pause import KEY

@unittest.skipUnless(os.getenv('LOCAL_CARD_PAUSE_TEST_DSN'), 'Disposable PostgreSQL required')
class PostgresPauseTests(unittest.TestCase):
    def test_repeated_money_and_pause_transfer_with_durable_expiry(self):
        dsn=os.environ['LOCAL_CARD_PAUSE_TEST_DSN'];schema='pause_test_'+uuid4().hex
        @contextmanager
        def database():
            with psycopg.connect(dsn,row_factory=dict_row) as conn:
                conn.execute('SET search_path TO '+schema)
                yield conn
        with psycopg.connect(dsn,autocommit=True) as conn:conn.execute('CREATE SCHEMA '+schema)
        try:
            with database() as conn:
                conn.execute('''CREATE TABLE rfid_cards(uid text PRIMARY KEY,balance_sum bigint,bonus_sum bigint,metadata jsonb,last_seen_at timestamptz,updated_at timestamptz);
                CREATE TABLE wash_sessions(id bigserial PRIMARY KEY,bonus_remaining_sum bigint DEFAULT 0,source text DEFAULT 'card',card_uid text,metadata jsonb DEFAULT '{}');
                CREATE TABLE rfid_card_ledger(card_uid text,wash_session_id bigint,direction text,reason text,amount_sum bigint,duration_seconds int,balance_after_sum bigint,raw_payload jsonb);
                CREATE TABLE system_events(level text,event_type text,source text,message text,context jsonb,wash_session_id bigint);''')
                conn.execute("INSERT INTO rfid_cards VALUES('test-card',0,0,'{\"name\":\"kept\"}',now(),now())")
                sid=conn.execute('INSERT INTO wash_sessions DEFAULT VALUES RETURNING id').fetchone()['id'];conn.commit()
            def runtime():
                r=WashRuntime();r._flush_usage_locked=Mock();r._close_session_locked=Mock()
                def credit(*args):
                    with database() as c:
                        r.active_session_id=c.execute('INSERT INTO wash_sessions DEFAULT VALUES RETURNING id').fetchone()['id'];c.commit()
                r._record_credit_locked=credit
                return r
            r=runtime();r.active_session_id=sid
            r.state.update(creditSum=10000,_creditFloat=10000,bonusSum=2000,_bonusFloat=2000,
                           _pauseBudgetInitialized=True,_pauseBudgetFloat=24.25,freePauseRemaining=25)
            with patch('app.wash_logic.db',database):
                for remaining in [24.25,24.25,0,0,0]:
                    r.state.update(_pauseBudgetInitialized=True,_pauseBudgetFloat=remaining)
                    r._save_remaining_to_customer_card_locked('test-card',{})
                    with database() as c:
                        card=c.execute('SELECT * FROM rfid_cards').fetchone()
                    self.assertEqual((card['balance_sum'],card['bonus_sum']),(10000,2000))
                    self.assertEqual(card['metadata']['name'],'kept')
                    r=runtime();r._use_customer_balance_locked('test-card',10000,{})
                    self.assertEqual(r.state['creditSum'],10000)
                    self.assertEqual(r.state['bonusSum'],2000)
                    self.assertEqual(r.state['_pauseBudgetFloat'],remaining)
                    with database() as c:
                        persisted=c.execute('SELECT metadata FROM wash_sessions WHERE id=%s',(r.active_session_id,)).fetchone()['metadata']
                    self.assertEqual(persisted['free_pause_remaining'],remaining)
                    self.assertTrue(persisted['pause_budget_initialized'])
                r._save_remaining_to_customer_card_locked('test-card',{})
                with database() as c:
                    m=c.execute('SELECT metadata FROM rfid_cards').fetchone()['metadata']
                    m[KEY]['wash']['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
                    c.execute('UPDATE rfid_cards SET metadata=%s',(Jsonb(m),));c.commit()
                r=runtime();r._use_customer_balance_locked('test-card',10000,{})
                self.assertEqual(r.state['_pauseBudgetFloat'],60)
                self.assertEqual((r.state['creditSum'],r.state['bonusSum']),(10000,2000))
        finally:
            with psycopg.connect(dsn,autocommit=True) as conn:conn.execute('DROP SCHEMA '+schema+' CASCADE')
