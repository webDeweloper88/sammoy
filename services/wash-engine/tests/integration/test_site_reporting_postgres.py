"""Owner totals on disposable PostgreSQL: cross-day sessions, card turnover, VIP."""
import os,unittest
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app import site_reporting

@unittest.skipUnless(os.getenv('CASH_TEST_DSN'),'Disposable PostgreSQL required')
class SiteReportingPostgresTests(unittest.TestCase):
    def setUp(self):
        self.c=psycopg.connect(os.environ['CASH_TEST_DSN'],row_factory=dict_row)
        assert self.c.info.dbname=='retention_test'
        self.schema='site_'+uuid4().hex;self.c.execute('CREATE SCHEMA '+self.schema);self.c.execute('SET search_path TO '+self.schema)
        self.c.execute(SCHEMA_SQL)
        self.sid=self.c.execute("INSERT INTO wash_sessions(started_at,source) VALUES('2026-10-17T20:00:00Z','cash') RETURNING id").fetchone()['id']
        self.vip=self.c.execute("INSERT INTO wash_sessions(source) VALUES('vip') RETURNING id").fetchone()['id']
        for provider,amount,bonus,status in [('cash',10000,1000,'credited'),('click',25000,2500,'credited'),('card',80000,0,'credited'),('vip',90000,0,'credited'),('admin',10000,0,'credited'),('click',20000,0,'pending')]:
            self.c.execute("INSERT INTO payments(wash_session_id,provider,amount_sum,bonus_sum,status,created_at) VALUES(%s,%s,%s,%s,%s,'2026-10-18T20:00:00Z')",(self.sid,provider,amount,bonus,status))
        for sid,spent,bonus in [(self.sid,8000,1000),(self.vip,12000,0)]:
            self.c.execute("INSERT INTO mode_usage(wash_session_id,mode,spent_sum,bonus_spent_sum,duration_ms,started_at) VALUES(%s,'water',%s,%s,3000,'2026-10-18T20:00:00Z')",(sid,spent,bonus))
        self.c.execute("INSERT INTO rfid_cards(uid) VALUES('ABC')")
        for reason,amount in [('save_remaining',50000),('use_balance',50000)]:
            self.c.execute("INSERT INTO rfid_card_ledger(card_uid,wash_session_id,direction,reason,amount_sum,created_at) VALUES('ABC',%s,'credit',%s,%s,'2026-10-18T20:00:00Z')",(self.sid,reason,amount))
        self.c.commit()
        @contextmanager
        def database():
            try:yield self.c
            finally:self.c.rollback()
        self.mock=patch.object(site_reporting,'db',database);self.mock.start()
    def tearDown(self):
        self.mock.stop();self.c.rollback();self.c.execute('DROP SCHEMA '+self.schema+' CASCADE');self.c.commit();self.c.close()
    def test_real_receipts_exclude_card_vip_admin_and_pending(self):
        r=site_reporting.local_report('2026-10-19','2026-10-19');s=r['summary']
        self.assertEqual((s['cash_sum'],s['click_sum'],s['receipts_sum']),(10000,25000,35000))
        self.assertEqual((s['bonus_granted_sum'],s['test_credit_sum']),(3500,10000))
        self.assertEqual((s['customer_saved_sum'],s['customer_used_sum']),(50000,50000))
        self.assertEqual(r['timeline'],[{'day':'2026-10-19','cash_sum':10000,'click_sum':25000}])
    def test_usage_does_not_depend_on_session_start_date(self):
        s=site_reporting.local_report('2026-10-19','2026-10-19')['summary']
        self.assertEqual((s['service_sum'],s['money_spent_sum'],s['bonus_spent_sum'],s['vip_virtual_spent_sum']),(8000,7000,1000,12000))
    def test_previous_day_is_empty(self):
        s=site_reporting.local_report('2026-10-18','2026-10-18')['summary']
        self.assertEqual(s['receipts_sum'],0);self.assertEqual(s['service_sum'],0)
