"""Real post ledger + replicated wallet, with IO deliberately mocked OFF only."""
import os
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
import unittest
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app.wallet_store import WALLET_SCHEMA_SQL,WalletStore
from app.wallet_replication import Authority,ReplicaReceiver,ReplicatedWallet,WalletUnavailable
from app.wallet_domain import WalletPolicy
from app.wallet_post import POST_SCHEMA_SQL
from app.wallet_payments import PAYMENT_SCHEMA_SQL
from app import wallet_post,wallet_payments,wash_logic,wallet_vip


@unittest.skipUnless(os.environ.get('WALLET_TEST_DSN'),'Disposable PostgreSQL required')
class PostAdapterTests(unittest.TestCase):
    def setUp(self):
        self.nodes=[]
        for index in range(3):
            conn=psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True,row_factory=dict_row)
            if conn.info.dbname!='wallet_test':raise RuntimeError('Refusing live database')
            schema='adapter_'+uuid4().hex
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            if index==0:
                conn.execute(SCHEMA_SQL);conn.execute(POST_SCHEMA_SQL);conn.execute(PAYMENT_SCHEMA_SQL)
                conn.autocommit=False
            else:conn.execute(WALLET_SCHEMA_SQL)
            self.nodes.append((conn,schema))
        self.local=self.nodes[0][0]
        self.primary=WalletStore(self.nodes[1][0],'SITE');self.backup=WalletStore(self.nodes[2][0],'SITE')
        receiver=ReplicaReceiver(self.backup,Authority('SITE',7,1,7))
        self.wallet=ReplicatedWallet(self.primary,Authority('SITE',1,1,7),receiver.stage,receiver.commit)
        self.wallet.execute('opening','CARD',{'action':'import_opening','amount_sum':35000},WalletPolicy())
        self.post_no=2
        @contextmanager
        def local_db():
            try:yield self.local
            except BaseException:self.local.rollback();raise
        def execute(operation,uid,command):return self.wallet.execute(operation,uid,command,WalletPolicy())
        self.patches=[patch.object(wallet_post,'db',local_db),patch.object(wallet_vip,'db',local_db),patch.object(wallet_payments,'db',local_db),patch.object(wash_logic,'db',local_db),
            patch.object(wallet_post.wallet_client,'discover_configuration',side_effect=lambda:{'local_post':self.post_no}),
            patch.object(wallet_post.wallet_client,'inspect',side_effect=self.primary.inspect),
            patch.object(wallet_post.wallet_client,'execute',side_effect=execute)]
        for p in self.patches:p.start()
        self.runtime=wash_logic.WashRuntime();self.runtime.shared_wallet_enabled=True
        self.runtime._apply_output_sync=lambda output:self.assertIsNone(output)
        self.runtime.state['lastIoOk']=True

    def tearDown(self):
        for p in self.patches:p.stop()
        for conn,schema in self.nodes:
            conn.rollback();conn.autocommit=True
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));conn.close()

    def tap(self):wallet_post.handle_card(self.runtime,'CARD',{})

    def test_load_cash_spend_return_and_other_post_pause_budget(self):
        self.tap();self.assertEqual(self.runtime.state['creditSum'],35000)
        self.runtime.add_credit(10000,'bill_pulse',idempotency_key='test-cash')
        spent=self.runtime._charge_active_locked('water',480)
        self.assertEqual(spent,12000)
        self.runtime.state['_pauseBudgetFloat']=10
        self.runtime.state['freePauseRemaining']=10
        self.tap();self.assertEqual(self.runtime.state['creditSum'],0)
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],33000)
        self.post_no=7;self.tap()
        self.assertEqual(self.runtime.state['creditSum'],33000)
        self.assertEqual(self.runtime.state['_pauseBudgetFloat'],10)
        self.assertEqual(self.primary.inspect('CARD'),self.backup.inspect('CARD'))

    def test_lost_return_reply_and_cash_while_pending_are_not_lost(self):
        self.tap()
        original=wallet_post.wallet_client.execute.side_effect
        failed=False
        def lose(operation,uid,command):
            nonlocal failed
            result=original(operation,uid,command)
            if command['action']=='complete_return' and not failed:
                failed=True;raise WalletUnavailable('reply lost')
            return result
        wallet_post.wallet_client.execute.side_effect=lose
        with self.assertRaises(WalletUnavailable):self.tap()
        self.assertTrue(self.runtime.state['walletTransferPending'])
        self.runtime.add_credit(5000,'bill_pulse',idempotency_key='cash-after-return')
        self.tap()
        self.assertEqual(self.runtime.state['creditSum'],5000)
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],35000)
        paid=self.local.execute("SELECT sum(amount_sum) AS amount FROM payments WHERE provider='cash'").fetchone()['amount'];self.local.commit()
        self.assertEqual(paid,5000)
        self.assertIsNone(wallet_post.assignment())

    def test_late_click_credits_wallet_not_new_post_session(self):
        self.tap();origin=self.runtime.active_session_id
        intent=uuid4();gateway=uuid4()
        row=self.local.execute("INSERT INTO click_payment_intents(id,gateway_intent_id,amount_sum,status,wallet_origin_session_id,wallet_origin_uid) VALUES(%s,%s,20000,'paid',%s,'CARD') RETURNING *",
                               (intent,gateway,origin)).fetchone();self.local.commit()
        self.tap();self.post_no=7;self.tap()
        balance=self.runtime.state['creditSum']
        destination=wallet_payments.credit_confirmed(self.runtime,row)
        self.assertEqual(destination,'wallet')
        wallet_payments.credit_confirmed(self.runtime,row)
        self.assertEqual(self.runtime.state['creditSum'],balance)
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],20000)
        count=self.local.execute("SELECT count(*) AS n FROM payments WHERE idempotency_key=%s",('click:'+str(gateway),)).fetchone()['n'];self.local.commit()
        self.assertEqual(count,1)

    def test_unknown_online_origin_creates_recovery_not_post_credit(self):
        self.runtime.add_credit(7000,'bill_pulse',idempotency_key='other-customer')
        row={'id':uuid4(),'gateway_intent_id':uuid4(),'amount_sum':20000,'wallet_origin_session_id':None,'wallet_origin_uid':None}
        self.assertEqual(wallet_payments.credit_confirmed(self.runtime,row),'recovery')
        self.assertEqual(wallet_payments.credit_confirmed(self.runtime,row),'recovery')
        self.assertEqual(self.runtime.state['creditSum'],7000)
        amount=self.local.execute("SELECT sum(amount_sum) AS amount FROM recovery_credits WHERE status='unclaimed'").fetchone()['amount'];self.local.commit()
        self.assertEqual(amount,20000)

    def test_different_card_cannot_take_current_customer_balance(self):
        self.tap()
        with self.assertRaises(Exception):wallet_post.handle_card(self.runtime,'OTHER',{})
        self.assertEqual(self.runtime.state['creditSum'],35000)

    def test_pending_return_recovered_after_runtime_restart(self):
        self.tap();original=wallet_post.wallet_client.execute.side_effect
        def fail(operation,uid,command):
            if command['action']=='complete_return':raise WalletUnavailable('down')
            return original(operation,uid,command)
        wallet_post.wallet_client.execute.side_effect=fail
        with self.assertRaises(WalletUnavailable):self.tap()
        self.assertIsNotNone(wallet_post.pending_job())
        old=self.runtime
        self.runtime=wash_logic.WashRuntime();self.runtime.shared_wallet_enabled=True
        self.runtime._apply_output_sync=lambda output:self.assertIsNone(output)
        self.runtime.state.update(old.state);self.runtime.active_session_id=old.active_session_id
        self.runtime.active_session_source=old.active_session_source
        wallet_post.wallet_client.execute.side_effect=original
        self.tap()
        self.assertEqual(self.runtime.state['creditSum'],0)
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],35000)

    def configure_vip(self):
        self.wallet.execute('vip-config','VIP',{'action':'configure_vip','profile':{'id':1,'code':'VIP','name':'VIP','enabled':True,'grant_seconds':600,'max_uses_per_day':1}},WalletPolicy())

    def test_vip_continues_on_other_post_without_new_daily_grant(self):
        self.configure_vip();wallet_vip.handle_card(self.runtime,'VIP',{})
        self.assertEqual(self.runtime.active_session_source,'vip')
        self.assertEqual(self.runtime.state['creditSum'],15000)
        self.runtime._charge_active_locked('water',240)
        self.runtime.state['_pauseBudgetFloat']=10;self.runtime.state['freePauseRemaining']=10
        wallet_vip.handle_card(self.runtime,'VIP',{})
        self.assertEqual(self.runtime.state['creditSum'],0)
        self.post_no=7;wallet_vip.handle_card(self.runtime,'VIP',{})
        self.assertEqual(self.runtime.state['creditSum'],9000)
        self.assertEqual(self.runtime.state['_pauseBudgetFloat'],10)
        shared=self.primary.inspect('VIP')['state']
        self.assertEqual(shared['vip_uses'],{})
        self.assertEqual(self.nodes[1][0].execute("SELECT sum(used) AS uses FROM shared_wallet_vip_uses WHERE uid='VIP'").fetchone()['uses'],1)
        self.assertEqual(shared['wallet_sum'],0)

    def test_physical_cash_during_vip_is_recoverable_not_virtual_credit(self):
        self.configure_vip();wallet_vip.handle_card(self.runtime,'VIP',{})
        for _ in range(2):self.runtime._accept_cash_locked(5000,'bill_pulse',1,{'rising_count':1})
        self.assertEqual(self.runtime.state['creditSum'],15000)
        held=self.local.execute("SELECT sum(amount_sum) AS amount FROM recovery_credits WHERE status='unclaimed'").fetchone()['amount'];self.local.commit()
        self.assertEqual(held,5000)
        self.assertEqual(self.runtime.state['walletCashHeld'],5000)

    def test_same_card_recovery_returns_its_money_after_long_outage(self):
        self.tap();ctx=wallet_post.assignment()
        self.local.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status) VALUES(%s,35000,'power','unclaimed')",(ctx['session_id'],))
        self.local.execute("UPDATE wash_sessions SET status='ended',ended_at=now(),final_credit_sum=35000 WHERE id=%s",(ctx['session_id'],));self.local.commit()
        self.runtime.active_session_id=None;self.runtime.state.update(creditSum=0,_creditFloat=0)
        self.tap()
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],35000)
        self.assertEqual(self.runtime.state['creditSum'],0)
        status=self.local.execute('SELECT status FROM recovery_credits WHERE wash_session_id=%s',(ctx['session_id'],)).fetchone()['status'];self.local.commit()
        self.assertEqual(status,'claimed')

    def test_recovery_retry_credits_once_and_cannot_change_card(self):
        self.patches.append(patch.object(wallet_payments.wallet_client,'enabled',return_value=True));self.patches[-1].start()
        session=self.local.execute("INSERT INTO wash_sessions(status,source,final_credit_sum) VALUES('ended','cash',5000) RETURNING id").fetchone()['id']
        row=self.local.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason,status) VALUES(%s,5000,'cash_during_vip','unclaimed') RETURNING id",(session,)).fetchone();self.local.commit()
        original=wallet_post.wallet_client.execute.side_effect
        def lose(operation,uid,command):
            original(operation,uid,command);raise WalletUnavailable('reply lost')
        wallet_post.wallet_client.execute.side_effect=lose
        with self.assertRaises(WalletUnavailable):wallet_payments.restore_recovery(row['id'],'CARD','owner')
        with self.assertRaises(Exception):wallet_payments.restore_recovery(row['id'],'OTHER','owner')
        wallet_post.wallet_client.execute.side_effect=original
        wallet_payments.restore_recovery(row['id'],'CARD','owner');wallet_payments.restore_recovery(row['id'],'CARD','owner')
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],40000)
        self.assertEqual(self.local.execute('SELECT status FROM recovery_credits WHERE id=%s',(row['id'],)).fetchone()['status'],'claimed');self.local.commit()

    def test_compact_vip_daily_counter_still_blocks_second_grant(self):
        self.configure_vip()
        command={'post_no':2,'assignment_id':'first'}
        self.wallet.execute('first-vip','VIP',{**command,'action':'grant_vip','visit_id':'first-visit'},WalletPolicy())
        self.wallet.execute('empty-vip','VIP',{**command,'action':'checkpoint_vip','remaining_sum':0,'pause_millis':0},WalletPolicy())
        self.wallet.execute('return-vip','VIP',{**command,'action':'return_vip'},WalletPolicy())
        from app.wallet_domain import WalletConflict
        with self.assertRaises(WalletConflict):self.wallet.execute('second-vip','VIP',{'post_no':7,'assignment_id':'second','action':'grant_vip','visit_id':'second-visit'},WalletPolicy())
        for node in (1,2):self.assertEqual(self.nodes[node][0].execute("SELECT sum(used) AS uses FROM shared_wallet_vip_uses WHERE uid='VIP'").fetchone()['uses'],1)
