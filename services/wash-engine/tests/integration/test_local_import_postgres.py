import os
import unittest
from uuid import uuid4
from contextlib import contextmanager
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app.wallet_store import WalletStore,WALLET_SCHEMA_SQL
from app.wallet_domain import WalletPolicy,WalletConflict
from app.wallet_replication import Authority,ReplicaReceiver,ReplicatedWallet,WalletUnavailable
from app import local_balance_import as migration
from app.customer_registry import page

@unittest.skipUnless(os.getenv('WALLET_TEST_DSN'),'Disposable PostgreSQL required')
class LocalImportTests(unittest.TestCase):
    def setUp(self):
        self.nodes=[]
        for n in range(3):
            c=psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True,row_factory=dict_row)
            assert c.info.dbname=='wallet_test'
            s='import_'+uuid4().hex;c.execute('CREATE SCHEMA '+s);c.execute('SET search_path TO '+s)
            c.execute(SCHEMA_SQL if n==0 else WALLET_SCHEMA_SQL);self.nodes.append((c,s))
        self.local=self.nodes[0][0];self.local.autocommit=False
        self.primary=WalletStore(self.nodes[1][0],'SITE');self.standby=WalletStore(self.nodes[2][0],'SITE')
        receiver=ReplicaReceiver(self.standby,Authority('SITE',7,1,7))
        self.wallet=ReplicatedWallet(self.primary,Authority('SITE',1,1,7),receiver.stage,receiver.commit)
        self.cfg={'enabled':True,'site_id':'SITE','local_post':2,'primary_post':1,'standby_post':7,'generation':1,'single_node':False}
        self.local.execute("INSERT INTO rfid_cards(uid,card_type,status,enabled,balance_sum,display_name) VALUES('ABCD','customer','active',true,35000,'Client')");self.local.commit()
        @contextmanager
        def db():
            try:yield self.local
            except BaseException:self.local.rollback();raise
        self.lose_reply=False;self.requests=[]
        def rpc(cfg,post,action,payload):
            self.requests.append(payload)
            result=self.wallet.execute(payload['operation_id'],payload['uid'],payload['command'],WalletPolicy())
            if self.lose_reply:self.lose_reply=False;raise WalletUnavailable('reply lost')
            return result
        self.patches=[patch.object(migration,'db',db),patch.object(migration,'configuration',return_value=self.cfg),patch.object(migration,'discover_configuration',return_value=self.cfg),patch.object(migration,'rpc',side_effect=rpc)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.local.rollback();self.local.autocommit=True
        for c,s in self.nodes:c.execute('DROP SCHEMA '+s+' CASCADE');c.close()
    def transfer(self):return migration.transfer('ABCD',35000,'IMPORT ABCD 35000',{'login':'owner'})
    def source(self):return self.local.execute("SELECT balance_sum,enabled FROM rfid_cards WHERE uid='ABCD'").fetchone()
    def test_success_clears_source_only_after_replicated_wallet_ack(self):
        self.transfer();self.assertEqual(self.source(),{'balance_sum':0,'enabled':False})
        self.assertEqual(self.primary.inspect('ABCD'),self.standby.inspect('ABCD'))
        state=self.primary.inspect('ABCD')['state'];self.assertEqual(state['wallet_sum'],35000)
        self.assertEqual(state['opening_sum'],35000);self.assertEqual(state['external_income_sum'],0)
        self.transfer();self.assertEqual(len(self.requests),1)
        self.assertEqual(self.local.execute('SELECT count(*) AS n FROM rfid_card_ledger').fetchone()['n'],1)
    def test_lost_reply_keeps_frozen_source_and_retries_same_operation(self):
        self.lose_reply=True
        with self.assertRaises(WalletUnavailable):self.transfer()
        self.assertEqual(self.source(),{'balance_sum':35000,'enabled':False})
        self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],35000)
        self.transfer();self.assertEqual(self.requests[0],self.requests[1]);self.assertEqual(self.source()['balance_sum'],0)
        self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],35000)
    def test_missing_standby_preserves_source_and_no_confirmed_wallet_credit(self):
        self.wallet.remote_stage=lambda payload:(_ for _ in ()).throw(WalletUnavailable('offline'))
        with self.assertRaises(WalletUnavailable):self.transfer()
        self.assertEqual(self.source(),{'balance_sum':35000,'enabled':False})
        self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],0)
    def test_wrong_confirmation_or_amount_never_freezes_source(self):
        for amount,confirmation in [(34000,'IMPORT ABCD 34000'),(35000,'wrong')]:
            with self.assertRaises(WalletConflict):migration.transfer('ABCD',amount,confirmation,{'login':'owner'})
        self.assertEqual(self.source(),{'balance_sum':35000,'enabled':True});self.assertFalse(self.requests)
    def test_blocked_source_is_not_reactivated(self):
        self.local.execute("UPDATE rfid_cards SET status='blocked',enabled=false");self.local.commit();self.transfer()
        state=self.primary.inspect('ABCD')['state'];self.assertFalse(state['enabled']);self.assertEqual(state['status'],'blocked')
    def test_receipt_cannot_be_reused_under_another_operation_to_double_money(self):
        self.transfer();payload=self.requests[0]
        self.wallet.execute('another-op','ABCD',payload['command'],WalletPolicy())
        self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],35000)
    def test_registry_pagination_and_assigned_money_are_distinct(self):
        self.transfer()
        self.wallet.execute('open-other','BCDE',{'action':'import_opening','amount_sum':1000},WalletPolicy())
        self.wallet.execute('load','ABCD',{'action':'reserve_load','post_no':7,'assignment_id':'a','visit_id':'v'},WalletPolicy())
        self.wallet.execute('service','@vip-profiles',{'action':'configure_service','value':{'profiles':[]}},WalletPolicy())
        result=page(self.primary,limit=1);self.assertEqual(result['next_after'],'ABCD')
        self.assertEqual(result['cards'][0]['balance_sum'],0);self.assertEqual(result['cards'][0]['assigned_sum'],35000)
        self.assertEqual(page(self.primary,after=result['next_after'])['cards'][0]['uid'],'BCDE')

    def test_local_amount_change_after_wallet_ack_requires_review_without_source_clear(self):
        def altered(cfg,post,action,payload):
            result=self.wallet.execute(payload['operation_id'],payload['uid'],payload['command'],WalletPolicy())
            self.local.execute("UPDATE rfid_cards SET balance_sum=36000 WHERE uid='ABCD'");self.local.commit()
            return result
        with patch.object(migration,'rpc',side_effect=altered):
            with self.assertRaises(WalletConflict):self.transfer()
        self.assertEqual(self.source(),{'balance_sum':36000,'enabled':False})
        self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],35000)
        self.assertEqual(self.local.execute('SELECT status FROM shared_wallet_local_imports').fetchone()['status'],'pending')
    def test_vip_target_rejects_import_and_preserves_frozen_money(self):
        self.wallet.execute('vip','ABCD',{'action':'configure_vip','profile':{'grant_seconds':60,'max_uses_per_day':1},'enabled':True,'status':'active'},WalletPolicy())
        with self.assertRaises(WalletConflict):self.transfer()
        self.assertEqual(self.source(),{'balance_sum':35000,'enabled':False})
        self.assertEqual(self.primary.inspect('ABCD')['state']['card_type'],'vip')
    def test_local_preview_uses_keyset_pages_without_moving_money(self):
        self.local.execute("INSERT INTO rfid_cards(uid,balance_sum) VALUES('BCDE',1000)");self.local.commit()
        result=migration.preview(limit=1);self.assertEqual(result['next_after'],'ABCD')
        self.assertEqual(migration.preview(after=result['next_after'])['cards'][0]['uid'],'BCDE')
        self.assertEqual(self.source(),{'balance_sum':35000,'enabled':True});self.assertFalse(self.requests)
    def test_setup_stages_balances_without_crediting_wallet_or_losing_original_flags(self):
        migration.stage_all(self.local,self.cfg,{'login':'installer'});self.local.commit()
        self.assertEqual(self.source(),{'balance_sum':35000,'enabled':False});self.assertFalse(self.requests)
        self.assertTrue(self.local.execute('SELECT source_snapshot FROM shared_wallet_local_imports').fetchone()['source_snapshot']['enabled'])
        self.transfer();self.assertTrue(self.primary.inspect('ABCD')['state']['enabled'])
        self.assertEqual(self.requests[0]['command']['actor'],'owner')

    def test_existing_bonus_is_imported_without_new_award(self):
        self.local.execute("UPDATE rfid_cards SET bonus_sum=3000 WHERE uid='ABCD'");self.local.commit()
        with patch('app.wallet_client.require_bonus_support') as support:
            migration.transfer('ABCD',35000,'IMPORT ABCD 35000',{'login':'owner'})
            support.assert_called_once_with(self.cfg)
        state=self.primary.inspect('ABCD')['state']
        self.assertEqual((state['wallet_sum'],state['wallet_bonus_sum'],state['opening_sum'],state['external_income_sum']),(35000,3000,32000,0))
        row=self.local.execute("SELECT balance_sum,bonus_sum FROM rfid_cards WHERE uid='ABCD'").fetchone()
        self.assertEqual((row['balance_sum'],row['bonus_sum']),(0,0))
