import os
import unittest
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app.financial_ids import FINANCIAL_IDS_SQL
from app import wallet_post

@unittest.skipUnless(os.getenv('FINANCIAL_TEST_DSN'),'Disposable PostgreSQL required')
class FinancialIdentityTests(unittest.TestCase):
    def setUp(self):
        self.conn=psycopg.connect(os.environ['FINANCIAL_TEST_DSN'],row_factory=dict_row)
        assert self.conn.info.dbname=='retention_test'
        self.schema='identity_'+uuid4().hex;self.conn.execute('CREATE SCHEMA '+self.schema)
        self.conn.execute('SET search_path TO '+self.schema);self.conn.execute(SCHEMA_SQL)
        self.session=self.conn.execute("INSERT INTO wash_sessions(source) VALUES('cash') RETURNING id").fetchone()['id'];self.conn.commit()
        @contextmanager
        def fake_db():yield self.conn
        self.patch=patch.object(wallet_post,'db',fake_db);self.patch.start()
    def tearDown(self):
        self.patch.stop();self.conn.rollback();self.conn.execute('DROP SCHEMA '+self.schema+' CASCADE');self.conn.commit();self.conn.close()
    def payment(self,provider='cash',key=None):
        return self.conn.execute("INSERT INTO payments(wash_session_id,provider,status,amount_sum,idempotency_key) VALUES(%s,%s,'credited',1000,%s) RETURNING id,raw_payload",(self.session,provider,key)).fetchone()
    def test_new_receipt_survives_numeric_id_reuse_and_post_number_change(self):
        a=self.payment();first=wallet_post.funding_since(self.session,0,1)[0]['id'];self.conn.commit()
        self.assertTrue(first.startswith('payment:'))
        self.assertEqual(first,wallet_post.funding_since(self.session,0,7)[0]['id'])
        self.conn.execute('DELETE FROM payments');self.conn.execute('ALTER SEQUENCE payments_id_seq RESTART WITH 1')
        b=self.payment('click');self.assertEqual(a['id'],b['id'])
        self.assertNotEqual(first,wallet_post.funding_since(self.session,0,1)[0]['id'])
    def test_repeat_migration_does_not_rename_old_or_new_receipts(self):
        self.conn.execute('DROP TRIGGER sammoy_payment_identity ON payments');legacy=self.payment()
        self.conn.execute(FINANCIAL_IDS_SQL);new=self.payment('click');self.conn.commit()
        expected=wallet_post.funding_since(self.session,0,2)
        self.assertEqual(expected[0]['id'],f"post:2:payment:{legacy['id']}")
        self.conn.execute(FINANCIAL_IDS_SQL);self.conn.commit()
        self.assertEqual(wallet_post.funding_since(self.session,0,2),expected)
        self.assertEqual(self.conn.execute('SELECT raw_payload FROM payments WHERE id=%s',(new['id'],)).fetchone()['raw_payload'],new['raw_payload'])
    def test_nv9_preserves_its_global_range_identity(self):
        self.payment(key='nv9:stream:1:2')
        self.assertEqual(wallet_post.funding_since(self.session,0,1)[0]['id'],'nv9:stream:1:2')
    def test_recovery_identity_is_persistent_and_not_based_on_numeric_id(self):
        sql="INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status) VALUES(%s,1000,'test','unclaimed') RETURNING id,metadata"
        a=self.conn.execute(sql,(self.session,)).fetchone();self.conn.commit()
        identity=a['metadata']['wallet_recovery_id'];self.assertTrue(identity.startswith('recovery:'))
        self.conn.execute(FINANCIAL_IDS_SQL);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT metadata FROM recovery_credits').fetchone()['metadata']['wallet_recovery_id'],identity)
        self.conn.execute('DELETE FROM recovery_credits');self.conn.execute('ALTER SEQUENCE recovery_credits_id_seq RESTART WITH 1')
        b=self.conn.execute(sql,(self.session,)).fetchone()
        self.assertEqual(a['id'],b['id']);self.assertNotEqual(identity,b['metadata']['wallet_recovery_id'])
