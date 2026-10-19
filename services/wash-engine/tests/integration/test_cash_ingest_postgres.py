"""NV9 crash and retry contracts against an isolated disposable schema."""
import os
import unittest
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app.wash_logic import WashRuntime
from app import cash_ingest

@unittest.skipUnless(os.getenv('CASH_TEST_DSN'),'Disposable PostgreSQL required')
class CashIngestTests(unittest.TestCase):
    def setUp(self):
        self.conn=psycopg.connect(os.environ['CASH_TEST_DSN'],row_factory=dict_row)
        assert self.conn.info.dbname=='retention_test'
        self.schema='cash_'+uuid4().hex
        self.conn.execute('CREATE SCHEMA '+self.schema);self.conn.execute('SET search_path TO '+self.schema)
        self.conn.execute(SCHEMA_SQL);self.conn.commit()
        self.stream=uuid4().hex;self.runtime=WashRuntime();self.runtime.params['billPulseSum']=1000
        self.fail_write=False;self.lose_commit=False
        outer=self
        class Connection:
            def execute(self,sql,*args):
                if outer.fail_write and 'INSERT INTO cash_events' in sql:
                    outer.fail_write=False;raise RuntimeError('write failure')
                return outer.conn.execute(sql,*args)
            def commit(self):
                outer.conn.commit()
                if outer.lose_commit:
                    outer.lose_commit=False;raise RuntimeError('commit reply lost')
        @contextmanager
        def fake_db():
            try:yield Connection()
            except BaseException:outer.conn.rollback();raise
        self.fake_db=fake_db
        self.override=patch.object(cash_ingest,'db',fake_db);self.override.start()
    def tearDown(self):
        self.override.stop();self.conn.rollback();self.conn.execute('DROP SCHEMA '+self.schema+' CASCADE');self.conn.commit();self.conn.close()
    def capture(self,total,runtime=None,recover=False):return cash_ingest.capture(runtime or self.runtime,{'nv9_stream_id':self.stream,'nv9_pulses':total},recover=recover)
    def count(self,table):return self.conn.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
    def test_duplicate_restart_and_new_range_do_not_double_credit(self):
        self.capture(3);self.assertEqual(self.runtime.state['creditSum'],3000)
        self.capture(3);self.assertEqual(self.count('payments'),1)
        fresh=WashRuntime();fresh.params['billPulseSum']=1000
        self.capture(3,fresh,recover=True);self.assertEqual(fresh.state['creditSum'],0)
        self.capture(5);self.assertEqual(self.runtime.state['creditSum'],5000)
        self.assertEqual(self.count('payments'),2);self.assertEqual(self.count('cash_events'),2)
        self.assertEqual(self.conn.execute('SELECT sum(pulse_count) AS n FROM cash_events').fetchone()['n'],5)
    def test_rollback_retries_without_losing_or_publishing_money(self):
        self.fail_write=True
        with self.assertRaises(RuntimeError):self.capture(2)
        self.assertEqual(self.runtime.state['creditSum'],0)
        for table in ('payments','cash_events','wash_sessions','app_settings'):self.assertEqual(self.count(table),0,table)
        self.capture(2);self.assertEqual(self.runtime.state['creditSum'],2000);self.assertEqual(self.count('payments'),1)
    def test_lost_commit_reply_reconciles_new_session_without_duplicate(self):
        self.lose_commit=True
        with self.assertRaises(RuntimeError):self.capture(2)
        self.assertEqual(self.runtime.state['creditSum'],0);self.assertEqual(self.count('payments'),1)
        self.capture(2);self.assertEqual(self.runtime.state['creditSum'],2000);self.assertIsNotNone(self.runtime.active_session_id)
        self.assertEqual(self.count('payments'),1)
    def test_lost_reply_followed_by_more_pulses_reconciles_before_addition(self):
        self.lose_commit=True
        with self.assertRaises(RuntimeError):self.capture(2)
        self.capture(3);self.assertEqual(self.runtime.state['creditSum'],3000)
        self.assertEqual(self.conn.execute('SELECT paid_sum FROM wash_sessions').fetchone()['paid_sum'],3000)
    def test_startup_unowned_cash_is_held_for_recovery(self):
        self.capture(4,recover=True);self.capture(4,recover=True)
        self.assertEqual(self.runtime.state['creditSum'],0);self.assertEqual(self.count('recovery_credits'),1)
        self.assertEqual(self.conn.execute('SELECT amount_sum FROM recovery_credits').fetchone()['amount_sum'],4000)
    def test_vip_and_license_locked_cash_are_not_discarded_or_mixed(self):
        self.runtime.active_session_source='vip';self.runtime.state['creditSum']=9000
        self.capture(1);self.assertEqual(self.runtime.state['creditSum'],9000)
        self.runtime.active_session_source=None;self.runtime.state['licenseLocked']=True
        self.capture(2);self.assertEqual(self.runtime.state['creditSum'],9000);self.assertEqual(self.count('recovery_credits'),2)
    def test_counter_rollback_is_rejected_and_different_stream_is_independent(self):
        self.capture(2)
        with self.assertRaises(RuntimeError):self.capture(1)
        self.stream=uuid4().hex;self.capture(1);self.assertEqual(self.runtime.state['creditSum'],3000)

    def test_engine_baseline_preserves_pending_pulses_as_recovery(self):
        from unittest.mock import Mock
        self.runtime._get_io_sync=Mock(return_value={'inputs':{},'nv9_stream_id':self.stream,'nv9_pulses':3})
        self.runtime._baseline_pulse_counters()
        self.assertEqual(self.runtime.state['creditSum'],0)
        self.assertEqual(self.count('payments'),1)
        self.assertEqual(self.count('recovery_credits'),1)
        self.assertFalse(self.runtime._nv9_startup_pending)
    def test_tick_consumes_durable_cash_once_and_never_uses_legacy_credit_path(self):
        from unittest.mock import Mock
        from app.io_safety import OUTPUTS
        r=self.runtime;r._nv9_startup_pending=False
        r._get_io_sync=Mock(return_value={'inputs':{'total_stop':False},'nv9_stream_id':self.stream,'nv9_pulses':2,
            'modbus_ok':True,'poll_age_seconds':0,'outputs':dict.fromkeys(OUTPUTS,False),'controller_boot_id':'boot','safety_trip_seq':0})
        for name in ('_get_rfid_events_sync','_apply_output_sync','_all_off_sync','_record_credit_locked',
                     '_track_usage_locked','_flush_usage_locked','_heartbeat_session_locked','_maybe_cleanup_retention_locked'):
            setattr(r,name,Mock(return_value={} if name=='_get_rfid_events_sync' else None))
        r.tick();r.tick()
        self.assertEqual(r.state['creditSum'],2000);self.assertEqual(self.count('payments'),1)
        r._record_credit_locked.assert_not_called()

    def test_held_commit_reply_loss_recovers_display_without_another_payment(self):
        self.lose_commit=True
        with self.assertRaises(RuntimeError):self.capture(2,recover=True)
        self.capture(2,recover=True);self.capture(2,recover=True)
        self.assertEqual(self.runtime.state['walletCashHeld'],2000)
        self.assertEqual(self.count('payments'),1);self.assertEqual(self.count('recovery_credits'),1)
    def test_nv9_wallet_receipt_is_not_derived_from_reusable_sql_id(self):
        from app import wallet_post
        self.capture(2)
        with patch.object(wallet_post,'db',self.fake_db):
            a=wallet_post.funding_since(self.runtime.active_session_id,0,1)
            b=wallet_post.funding_since(self.runtime.active_session_id,0,7)
        self.assertEqual(a,b);self.assertEqual(a[0]['id'],f'nv9:{self.stream}:1:2')
    def test_processed_stream_updates_legacy_counter_baseline_on_retry(self):
        self.capture(2)
        fresh=WashRuntime();fresh.params['billPulseSum']=1000
        self.capture(2,fresh,recover=True)
        self.assertEqual(fresh.last_bill_pulses,2);self.assertEqual(fresh.state['creditSum'],0)
        self.assertEqual(self.count('payments'),1)
    def test_nv9_recovery_retry_uses_stable_receipt_after_uncertain_wallet_reply(self):
        from app import wallet_payments,wallet_post
        from unittest.mock import Mock
        self.capture(2,recover=True)
        recovery=self.conn.execute('SELECT id FROM recovery_credits').fetchone()['id']
        rpc=Mock(side_effect=[RuntimeError('wallet reply lost'),{'ok':True}])
        with patch.object(wallet_payments,'db',self.fake_db),patch.object(wallet_post,'assignment',return_value=None),\
             patch.object(wallet_payments.wallet_client,'enabled',return_value=True),\
             patch.object(wallet_payments.wallet_client,'discover_configuration',return_value={'local_post':1}),\
             patch.object(wallet_payments.wallet_client,'execute',rpc),\
             patch.object(wallet_payments.wallet_client,'inspect',return_value=None):
            with self.assertRaises(RuntimeError):wallet_payments.restore_recovery(recovery,'CARD','owner')
            wallet_payments.restore_recovery(recovery,'CARD','owner')
        self.assertEqual(rpc.call_args_list[0],rpc.call_args_list[1])
        self.assertEqual(rpc.call_args.args[0],f'nv9-recovery:{self.stream}:1:2')
        self.assertEqual(self.conn.execute('SELECT status FROM recovery_credits').fetchone()['status'],'claimed')
