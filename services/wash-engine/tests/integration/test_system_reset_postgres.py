"""Destructive reset verification in a fresh disposable schema only."""
import os
import unittest
from uuid import uuid4
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.main import SCHEMA_SQL
from app.wallet_store import WALLET_SCHEMA_SQL
from app.wallet_post import POST_SCHEMA_SQL
from app.system_reset import reset


@unittest.skipUnless(os.getenv('RESET_TEST_DSN'), 'Disposable PostgreSQL required')
class SystemResetPostgresTests(unittest.TestCase):
    def setUp(self):
        self.conn=psycopg.connect(os.environ['RESET_TEST_DSN'],row_factory=dict_row)
        assert self.conn.info.dbname=='retention_test'
        self.schema='reset_'+uuid4().hex
        self.conn.execute('CREATE SCHEMA '+self.schema)
        self.conn.execute('SET search_path TO '+self.schema)
        for schema in (SCHEMA_SQL,WALLET_SCHEMA_SQL,POST_SCHEMA_SQL):self.conn.execute(schema)
        self.conn.execute("INSERT INTO auth_users(login,role,display_name,password_hash) VALUES('admin','admin','Admin','unchanged-hash')")
        for key,value in {'wash_parameters':{'billPulseSum':2000},'kiosk_settings':{'brand':{'name':'TEST'}},'shared_wallet':{'enabled':True},'commissioning_state':{'complete':True},'license_settings':{'enabled':True},'nv9_cursor:teststream':{'total':10,'session_id':123,'receipt_id':'old'}}.items():
            self.conn.execute('INSERT INTO app_settings(setting_key,setting_value) VALUES(%s,%s)',(key,Jsonb(value)))
        self.conn.execute("INSERT INTO shared_wallet_cards(site_id,uid,state) VALUES('test','card','{\"balance\":11000}'::jsonb)")
        self.conn.execute("INSERT INTO wash_sessions(status,source,paid_sum,final_credit_sum) VALUES('ended','cash',10000,0)")
        self.conn.execute("INSERT INTO payments(provider,status,amount_sum,idempotency_key) VALUES('cash','credited',10000,'test-cash')")
        self.conn.commit()

    def tearDown(self):
        self.conn.rollback();self.conn.execute('DROP SCHEMA '+self.schema+' CASCADE');self.conn.commit();self.conn.close()

    def setting(self,key):
        row=self.conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=%s',(key,)).fetchone()
        return row['setting_value'] if row else None

    def test_settings_preserves_wallet_money_history_activation_and_cursor(self):
        reset(self.conn,'settings')
        self.assertIsNone(self.setting('wash_parameters'))
        self.assertIsNone(self.setting('kiosk_settings'))
        self.assertTrue(self.setting('commissioning_state')['complete'])
        self.assertTrue(self.setting('license_settings')['enabled'])
        self.assertEqual(self.setting('nv9_cursor:teststream')['total'],10)
        self.assertEqual(self.conn.execute('SELECT amount_sum FROM payments').fetchone()['amount_sum'],10000)
        self.assertEqual(self.conn.execute('SELECT state FROM shared_wallet_cards').fetchone()['state']['balance'],11000)

    def test_full_deletes_money_history_and_site_but_preserves_login_and_pulse_offset(self):
        reset(self.conn,'full')
        for table in ('payments','shared_wallet_cards','wash_sessions'):
            self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'],0)
        self.assertIsNone(self.setting('commissioning_state'))
        self.assertIsNone(self.setting('license_settings'))
        self.assertIsNone(self.setting('shared_wallet'))
        self.assertEqual(self.setting('nv9_cursor:teststream'),{'total':10})
        user=self.conn.execute('SELECT * FROM auth_users').fetchone()
        self.assertEqual(user['password_hash'],'unchanged-hash');self.assertEqual(user['auth_version'],2)

    def test_new_credit_after_api_confirmation_blocks_reset(self):
        self.conn.execute("INSERT INTO wash_sessions(status,source,paid_sum,final_credit_sum) VALUES('running','cash',1000,1000)")
        with self.assertRaises(RuntimeError):reset(self.conn,'full')
        self.assertIsNotNone(self.setting('kiosk_settings'))

    def test_unprocessed_pulses_block_reset_without_changing_cursor(self):
        with patch.dict(os.environ,{'RESET_NV9_STREAM':'teststream','RESET_NV9_TOTAL':'11'}):
            with self.assertRaises(RuntimeError):reset(self.conn,'full')
        self.assertEqual(self.setting('nv9_cursor:teststream')['total'],10)

    def test_unknown_mode_cannot_delete_anything(self):
        with self.assertRaises(ValueError):reset(self.conn,'other')
        self.assertIsNotNone(self.setting('kiosk_settings'))
