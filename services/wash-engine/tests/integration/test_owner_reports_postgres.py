"""Financial reports against disposable schemas, never production data."""
import os
import unittest
from uuid import uuid4
from contextlib import contextmanager
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app import main

@unittest.skipUnless(os.getenv('REPORT_TEST_DSN'),'Disposable PostgreSQL required')
class OwnerReportsTests(unittest.TestCase):
    def setUp(self):
        self.conn=psycopg.connect(os.environ['REPORT_TEST_DSN'],row_factory=dict_row)
        assert self.conn.info.dbname=='retention_test'
        self.schema='report_'+uuid4().hex
        self.conn.execute('CREATE SCHEMA '+self.schema)
        self.conn.execute('SET search_path TO '+self.schema)
        self.conn.execute(main.SCHEMA_SQL);self.conn.commit()
        @contextmanager
        def fake_db():yield self.conn
        self.override=patch.object(main,'db',fake_db);self.override.start()
    def tearDown(self):
        self.override.stop();self.conn.rollback()
        self.conn.execute('DROP SCHEMA '+self.schema+' CASCADE');self.conn.commit();self.conn.close()
    def session(self,source,paid,spent,remaining,status='ended'):
        return self.conn.execute('INSERT INTO wash_sessions(source,paid_sum,total_spent_sum,final_credit_sum,status) VALUES(%s,%s,%s,%s,%s) RETURNING id',(source,paid,spent,remaining,status)).fetchone()['id']
    def payment(self,sid,provider,amount):
        self.conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum) VALUES(%s,%s,'credited',%s)",(sid,provider,amount))
    def test_vip_virtual_credit_is_not_money_and_card_is_not_new_revenue(self):
        cash=self.session('cash',10000,6000,4000);self.payment(cash,'cash',10000)
        card=self.session('card',35000,10000,25000);self.payment(card,'card',35000)
        click=self.session('click',20000,20000,0);self.payment(click,'click',20000)
        vip=self.session('vip',9000,7000,2000);self.payment(vip,'vip',9000)
        self.conn.execute("INSERT INTO mode_usage(wash_session_id,mode,spent_sum,duration_ms) VALUES(%s,'water',6000,60000),(%s,'water',7000,70000)",(cash,vip))
        self.conn.commit()
        report=main.owner_reports_summary({'role':'owner'})
        self.assertEqual(report['modes'][0]['spent_sum'],6000)
        self.assertEqual(report['modes'][0]['vip_virtual_spent_sum'],7000)
        summary=report['summary']
        self.assertEqual(summary['closed_sessions'],4)
        self.assertEqual(summary['paid_sum'],65000)
        self.assertEqual(summary['spent_sum'],36000)
        self.assertEqual(summary['final_credit_sum'],29000)
        self.assertEqual(summary['vip_virtual_spent_sum'],7000)
        self.assertEqual(summary['external_revenue_sum'],30000)
        self.assertEqual(summary['credit_difference_sum'],0)
    def test_cash_filter_and_legacy_closed_status(self):
        cash=self.session('cash',10000,10000,0,'closed');self.payment(cash,'cash',10000)
        click=self.session('click',20000,20000,0);self.payment(click,'click',20000)
        self.conn.commit()
        summary=main.owner_reports_summary({'role':'owner'},payment_method='cash')['summary']
        self.assertEqual(summary['sessions'],1);self.assertEqual(summary['closed_sessions'],1)
        self.assertEqual(summary['external_revenue_sum'],10000)
