"""Real-money/bonus separation against disposable retention_test only."""
from unittest.mock import patch
from contextlib import ExitStack
from test_cash_ingest_postgres import CashIngestTests as BaseCash
from app import wash_logic,bonus_credit,wallet_payments,main
from app.wash_logic import WashRuntime
from uuid import uuid4
class BonusPostgresTests(BaseCash):
    def setUp(self):
        super().setUp()
        if self._testMethodName not in BaseCash.__dict__:self.runtime.params['topUpBonus']={'enabled':True,'percent':10}
        self.conn.execute(wallet_payments.PAYMENT_SCHEMA_SQL);self.conn.commit()
        self.stack=ExitStack()
        for module in [wash_logic,bonus_credit,wallet_payments,main]:self.stack.enter_context(patch.object(module,'db',self.fake_db))
    def tearDown(self):self.stack.close();super().tearDown()
    def test_bonus_nv9_rollback_unknown_commit_and_repeat(self):
        self.fail_write=True
        with self.assertRaises(RuntimeError):self.capture(50)
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(0,0))
        self.lose_commit=True
        with self.assertRaises(RuntimeError):self.capture(50)
        self.runtime.params['topUpBonus']['percent']=50
        self.capture(50)
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(55000,5000))
        p=self.conn.execute('SELECT amount_sum,bonus_sum FROM payments').fetchone();self.assertEqual((p['amount_sum'],p['bonus_sum']),(50000,5000))
    def test_local_card_roundtrip_preserves_bonus_and_restart(self):
        self.capture(50)
        self.runtime._apply_rfid_card_locked('ABCD',{'seq':1})
        c=self.conn.execute('SELECT balance_sum,bonus_sum FROM rfid_cards').fetchone();self.assertEqual((c['balance_sum'],c['bonus_sum']),(55000,5000))
        self.assertEqual(self.runtime.state['bonusSum'],0)
        self.runtime._apply_rfid_card_locked('ABCD',{'seq':2})
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(55000,5000))
        self.runtime._charge_active_locked('water',80);self.runtime._heartbeat_session_locked()
        fresh=WashRuntime();fresh._recover_interrupted_sessions_sync()
        self.assertEqual((fresh.state['creditSum'],fresh.state['bonusSum']),(53000,3000))
        self.assertEqual(self.conn.execute('SELECT sum(bonus_sum) n FROM payments WHERE provider=\'cash\'').fetchone()['n'],5000)
    def test_confirmed_click_policy_snapshot_and_duplicate(self):
        ident=uuid4();gateway=uuid4()
        self.conn.execute("INSERT INTO click_payment_intents(id,gateway_intent_id,amount_sum,status) VALUES(%s,%s,50000,'paid')",(ident,gateway));self.conn.commit()
        with patch.object(main,'wash_runtime',self.runtime):
            main.apply_click_credit_once(ident)
            self.runtime.params['topUpBonus']['percent']=50
            main.apply_click_credit_once(ident)
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(55000,5000))
        self.assertEqual(self.count('payments'),1)
    def test_late_click_recovery_preserves_both_pockets(self):
        r=wallet_payments.credit_confirmed(self.runtime,{'id':uuid4(),'amount_sum':50000,'bonus_sum':5000,'wallet_origin_session_id':None})
        self.assertEqual(r,'recovery')
        row=self.conn.execute('SELECT amount_sum,bonus_sum FROM recovery_credits').fetchone();self.assertEqual((row['amount_sum'],row['bonus_sum']),(55000,5000))
    def test_bonus_reports_separate_revenue_from_service(self):
        self.capture(50)
        spent=self.runtime._charge_active_locked('water',240)
        self.runtime._track_usage_locked('water','active',240,spent);self.runtime._flush_usage_locked()
        report=main.owner_reports_summary({'login':'owner'},payment_method='all')
        self.assertEqual(report['summary']['external_revenue_sum'],50000)
        self.assertEqual(report['summary']['bonus_granted_sum'],5000)
        self.assertEqual(report['summary']['bonus_spent_sum'],5000)
        self.assertEqual(report['summary']['spent_sum'],1000)
        self.assertEqual(report['summary']['credit_difference_sum'],0)

    def test_click_lost_commit_reply_reconciles_before_next_billing(self):
        outer=self
        class Connection:
            def execute(self,sql,*args):
                if 'INSERT INTO payments' in sql:outer.payment_written=True
                return outer.conn.execute(sql,*args)
            def commit(self):
                outer.conn.commit()
                if getattr(outer,'payment_written',False):
                    outer.payment_written=False
                    raise RuntimeError('commit reply lost')
        from contextlib import contextmanager
        @contextmanager
        def ambiguous():yield Connection()
        with patch.object(bonus_credit,'db',ambiguous):
            with self.assertRaises(RuntimeError):self.runtime.add_credit(50000,'click',idempotency_key='click:lost',bonus_sum=5000)
        self.assertEqual(self.runtime.state['creditSum'],0)
        bonus_credit.reconcile(self.runtime)
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(55000,5000))
        self.runtime.add_credit(50000,'click',idempotency_key='click:lost',bonus_sum=25000)
        self.assertEqual((self.runtime.state['creditSum'],self.runtime.state['bonusSum']),(55000,5000))
        self.assertEqual(self.count('payments'),1)
