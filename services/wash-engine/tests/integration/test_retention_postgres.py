"""Runs only against the disposable retention_test database, never the live ledger."""
import os
import unittest
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app import retention
from app.wallet_post import POST_SCHEMA_SQL

@unittest.skipUnless(os.environ.get('RETENTION_TEST_DSN'),'Disposable PostgreSQL required')
class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.conn=psycopg.connect(os.environ['RETENTION_TEST_DSN'],row_factory=dict_row)
        assert self.conn.info.dbname=='retention_test'
        self.schema='test_'+uuid4().hex
        self.conn.execute('CREATE SCHEMA '+self.schema)
        self.conn.execute('SET search_path TO '+self.schema)
        self.conn.execute(SCHEMA_SQL);self.conn.execute(POST_SCHEMA_SQL);self.conn.commit()
        @contextmanager
        def fake_db():
            try:yield self.conn
            except BaseException:self.conn.rollback();raise
        self.override=patch.object(retention,'db',fake_db);self.override.start()
    def tearDown(self):
        self.override.stop();self.conn.rollback();self.conn.execute('DROP SCHEMA '+self.schema+' CASCADE');self.conn.commit();self.conn.close()
    def count(self,table):return self.conn.execute('SELECT count(*) AS count FROM '+table).fetchone()['count']
    def session(self,status='ended',age='13 months'):
        return self.conn.execute("INSERT INTO wash_sessions(status,started_at,ended_at) VALUES(%s,now()-%s::interval,CASE WHEN %s='ended' THEN now()-%s::interval ELSE NULL END) RETURNING id",(status,age,status,age)).fetchone()['id']
    def payment(self,session=None,age='13 months',provider='cash',status='credited'):
        self.conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,created_at) VALUES(%s,%s,%s,1000,now()-%s::interval)",(session,provider,status,age))
    def clean(self):
        self.conn.commit();result=retention.cleanup();self.assertTrue(result['ok'],result);return result
    def test_calendar_event_cutoff_and_financial_year(self):
        for age in ['1 month 1 minute','1 month -1 minute']:
            self.conn.execute("INSERT INTO system_events(level,event_type,source,message,created_at) VALUES('info','test','test','test',now()-%s::interval)",(age,))
        self.payment(age='12 months 1 minute');self.payment(age='12 months -1 minute')
        self.clean();self.assertEqual(self.count('system_events'),1);self.assertEqual(self.count('payments'),1)
    def test_unclaimed_credit_pins_money_and_trail(self):
        session=self.session()
        self.conn.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status) VALUES(%s,1744,'test','unclaimed')",(session,))
        self.conn.execute("INSERT INTO rfid_cards(uid,card_type,balance_sum) VALUES('CARD','customer',5000)")
        self.payment(session)
        self.conn.execute("INSERT INTO cash_events(wash_session_id,source_input,pulse_count,amount_sum,sum_per_pulse,created_at) VALUES(%s,'bill_pulse',1,1000,1000,now()-interval '13 months')",(session,))
        self.conn.execute("INSERT INTO mode_usage(wash_session_id,mode,started_at,ended_at) VALUES(%s,'water',now()-interval '13 months',now()-interval '13 months')",(session,))
        self.conn.execute("INSERT INTO rfid_card_ledger(card_uid,wash_session_id,direction,reason,created_at) VALUES('CARD',%s,'credit','save_remaining',now()-interval '13 months')",(session,))
        self.clean()
        for table in ['wash_sessions','payments','cash_events','mode_usage','rfid_card_ledger','recovery_credits']:self.assertEqual(self.count(table),1,table)
        self.assertEqual(self.conn.execute('SELECT balance_sum FROM rfid_cards').fetchone()['balance_sum'],5000)
        self.assertEqual(self.conn.execute('SELECT amount_sum FROM recovery_credits').fetchone()['amount_sum'],1744)
    def test_open_session_and_uncredited_click_survive(self):
        session=self.session('running');self.payment(session)
        ended=self.session();self.payment(ended,provider='click',status='paid')
        self.conn.execute("INSERT INTO click_payment_intents(id,amount_sum,status,created_at,updated_at) VALUES(%s,1000,'paid',now()-interval '13 months',now()-interval '13 months')",(uuid4(),))
        self.clean();self.assertEqual(self.count('wash_sessions'),2);self.assertEqual(self.count('payments'),2);self.assertEqual(self.count('click_payment_intents'),1)
    def test_closed_old_history_removed_recent_children_preserved(self):
        old=self.session();self.payment(old)
        recent_child=self.session();self.payment(recent_child,age='1 day')
        self.clean();self.assertEqual(self.count('wash_sessions'),1);self.assertEqual(self.count('payments'),1)
        self.assertEqual(self.conn.execute('SELECT id FROM wash_sessions').fetchone()['id'],recent_child)
    def test_finished_click_old_removed_pending_and_recent_updates_kept(self):
        for status,updated in [('credited','13 months'),('cancelled','13 months'),('prepared','13 months'),('credited','1 day')]:
            self.conn.execute("INSERT INTO click_payment_intents(id,amount_sum,status,created_at,updated_at) VALUES(%s,1000,%s,now()-interval '13 months',now()-%s::interval)",(uuid4(),status,updated))
        self.clean();self.assertEqual(self.count('click_payment_intents'),2)
    def test_admin_storage_and_click_cursor_read_real_sql(self):
        from app import admin_api
        from datetime import datetime
        from uuid import UUID
        for _ in range(3):self.conn.execute("INSERT INTO click_payment_intents(id,amount_sum,status) VALUES(%s,1000,'credited')",(uuid4(),))
        self.conn.commit()
        with patch.object(admin_api,'db',retention.db):
            first=admin_api.click_payments({},'credited',None,None,2)
            self.assertTrue(first['has_more']);self.assertEqual(len(first['intents']),2)
            cursor=first['next_cursor'];second=admin_api.click_payments({},'credited',datetime.fromisoformat(cursor['before_time']),UUID(cursor['before_id']),2)
            self.assertEqual(len(second['intents']),1);self.assertFalse(second['has_more'])
            self.assertNotIn(second['intents'][0]['id'],[x['id'] for x in first['intents']])
            storage=admin_api.storage({})
            self.assertEqual(storage['retention']['financial_months'],12)
            self.assertEqual(storage['retention']['event_months'],1)
            self.assertGreater(storage['database_bytes'],0)

    def test_pending_wallet_transfer_pins_closed_financial_trail(self):
        from psycopg.types.json import Jsonb
        session=self.session();self.payment(session)
        self.conn.execute("INSERT INTO shared_wallet_post_jobs(id,uid,kind,status,payload) VALUES(%s,'CARD','return','pending',%s)",(str(uuid4()),Jsonb({'session_id':session})))
        self.clean();self.assertEqual(self.count('payments'),1);self.assertEqual(self.count('wash_sessions'),1)
