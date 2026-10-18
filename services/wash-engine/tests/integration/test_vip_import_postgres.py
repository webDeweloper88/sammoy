import os,unittest
from uuid import uuid4
from contextlib import contextmanager
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.main import SCHEMA_SQL
from app.wallet_store import WalletStore,WALLET_SCHEMA_SQL
from app.wallet_domain import WalletPolicy,WalletConflict
from app.wallet_replication import Authority,ReplicaReceiver,ReplicatedWallet,WalletUnavailable
from app import vip_migration as migration,wallet_registry

@unittest.skipUnless(os.getenv('WALLET_TEST_DSN'),'Disposable PostgreSQL required')
class VipMigrationPostgresTests(unittest.TestCase):
    def setUp(self):
        self.nodes=[]
        for n in range(3):
            c=psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True,row_factory=dict_row)
            assert c.info.dbname=='wallet_test'
            s='vip_import_'+uuid4().hex;c.execute('CREATE SCHEMA '+s);c.execute('SET search_path TO '+s)
            c.execute(SCHEMA_SQL if n==0 else WALLET_SCHEMA_SQL);self.nodes.append((c,s))
        self.local=self.nodes[0][0];self.local.autocommit=False
        self.primary=WalletStore(self.nodes[1][0],'SITE');self.standby=WalletStore(self.nodes[2][0],'SITE')
        self.receiver=ReplicaReceiver(self.standby,Authority('SITE',7,1,7))
        self.wallet=ReplicatedWallet(self.primary,Authority('SITE',1,1,7),self.receiver.stage,self.receiver.commit)
        self.cfg={'enabled':True,'site_id':'SITE','local_post':2,'primary_post':1,'standby_post':7,'generation':1,'single_node':False,'visit_timeout_minutes':30,'peer_urls':{'1':'http://primary','2':'http://source','7':'http://backup'}}
        self.primary_cfg={**self.cfg,'local_post':1}
        profile=self.local.execute("INSERT INTO vip_profiles(code,name,enabled,grant_seconds,max_uses_per_day) VALUES('VIP','VIP',true,600,5) RETURNING id").fetchone()['id']
        self.local.execute("INSERT INTO rfid_cards(uid,card_type,vip_profile_id,display_name) VALUES('ABCD','vip',%s,'Client')",(profile,))
        for n in range(2):self.local.execute("INSERT INTO rfid_card_ledger(card_uid,direction,amount_sum,balance_after_sum,reason) VALUES('ABCD','grant',0,0,'vip_grant')")
        self.local.commit();self.lose_reply=False;self.requests=[];self.version=1;self.proofs={}
        @contextmanager
        def db():
            try:yield self.local
            except BaseException:self.local.rollback();raise
        @contextmanager
        def store_context(cfg):yield self.primary
        def rpc(cfg,post,action,payload):
            if action=='status':return {'vip_import_protocol':self.version,'local_post':post,'generation':1}
            if action=='vip-import-status':return self.proofs.get(post,{'vip_import_protocol':1,'local_post':post,'site_id':'SITE','generation':1,'enabled':True,'pending':0,'legacy':0})
            self.requests.append(payload)
            result=migration.import_on_primary(self.primary,self.primary_cfg,payload,2)
            if self.lose_reply:self.lose_reply=False;raise WalletUnavailable('reply lost')
            return result
        self.patches=[patch.object(migration,'db',db),patch.object(migration,'configuration',side_effect=lambda:self.cfg),patch.object(migration,'rpc',side_effect=rpc),patch.object(migration,'coordinator',return_value=self.wallet),patch.object(migration,'store_context',store_context),patch.object(wallet_registry,'coordinator',return_value=self.wallet),patch('app.wallet_client.discover_configuration',side_effect=lambda:self.cfg)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.local.rollback();self.local.autocommit=True
        for c,s in self.nodes:c.execute('DROP SCHEMA '+s+' CASCADE');c.close()
    def stage(self):migration.stage_all(self.local,self.cfg,{'login':'installer'});self.local.commit()
    def transfer(self):return migration.transfer('ABCD','IMPORT VIP ABCD',{'login':'owner'})
    def status(self):return self.local.execute('SELECT status FROM shared_wallet_vip_imports').fetchone()['status']
    def assert_replica(self):self.assertEqual(self.primary.state_digest(),self.standby.state_digest());self.assertEqual(self.primary.digest(),self.standby.digest())
    def test_freeze_and_replicate_profile_flags_and_daily_usage(self):
        self.stage();self.assertFalse(self.local.execute('SELECT enabled FROM rfid_cards').fetchone()['enabled']);self.transfer()
        self.assertEqual(self.status(),'done');self.assert_replica();s=self.primary.inspect('ABCD')['state'];self.assertEqual(s['card_type'],'vip');self.assertTrue(s['enabled']);self.assertEqual(s['wallet_sum'],0)
        day=self.local.execute("SELECT (now() AT TIME ZONE 'Asia/Tashkent')::date AS day").fetchone()['day']
        self.assertEqual(self.nodes[1][0].execute('SELECT used FROM shared_wallet_vip_uses WHERE uid=%s AND day=%s',('ABCD',day.isoformat())).fetchone()['used'],2)
        self.assertTrue(migration.gate_locked(self.primary))
    def test_lost_reply_and_new_operation_cannot_duplicate_usage(self):
        self.stage();self.lose_reply=True
        with self.assertRaises(WalletUnavailable):self.transfer()
        self.assertEqual(self.status(),'pending');self.transfer();self.assertEqual(self.status(),'done');self.assertEqual(self.requests[0],self.requests[1])
        payload={**self.requests[0],'operation_id':'vip-job:'+str(uuid4())};migration.import_on_primary(self.primary,self.primary_cfg,payload,2)
        self.assertEqual(self.nodes[1][0].execute('SELECT used FROM shared_wallet_vip_uses').fetchone()['used'],2);self.assert_replica()
    def test_backup_missing_keeps_frozen_source_pending(self):
        self.stage();self.wallet.remote_stage=lambda payload:(_ for _ in ()).throw(WalletUnavailable('offline'))
        with self.assertRaises(WalletUnavailable):self.transfer()
        self.assertEqual(self.status(),'pending');self.assertIsNone(self.primary.inspect('ABCD'))
    def test_old_backup_cannot_accept_import(self):
        self.stage();self.version=0
        with self.assertRaises(WalletUnavailable):self.transfer()
        self.assertEqual(self.status(),'pending');self.assertIsNone(self.primary.inspect('ABCD'))
    def test_money_uid_collision_is_not_overwritten(self):
        self.wallet.execute('money','ABCD',{'action':'import_opening','amount_sum':35000},WalletPolicy());self.stage()
        with self.assertRaises(WalletConflict):self.transfer()
        self.assertEqual(self.status(),'pending');self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],35000)
    def test_blocked_flag_preserved(self):
        self.local.execute("UPDATE rfid_cards SET enabled=false,status='blocked'");self.local.commit();self.stage();self.transfer()
        s=self.primary.inspect('ABCD')['state'];self.assertFalse(s['enabled']);self.assertEqual(s['status'],'blocked')
    def test_daily_usage_from_independent_posts_is_summed(self):
        self.stage();self.transfer();source={**self.requests[0]['snapshot'],'post_no':3}
        migration.import_on_primary(self.primary,self.primary_cfg,{'uid':'ABCD','snapshot':source,'operation_id':'vip-job:'+str(uuid4())},3)
        self.assertEqual(self.nodes[1][0].execute('SELECT used FROM shared_wallet_vip_uses').fetchone()['used'],4);self.assert_replica()
    def test_active_session_cannot_be_staged(self):
        self.local.execute("INSERT INTO wash_sessions(card_uid,source,status) VALUES('ABCD','vip','running')");self.local.commit()
        with self.assertRaises(WalletConflict):self.stage()
        self.assertTrue(self.local.execute('SELECT enabled FROM rfid_cards').fetchone()['enabled'])
    def test_invalid_confirmation_never_imports(self):
        self.stage()
        with self.assertRaises(WalletConflict):migration.transfer('ABCD','wrong',{'login':'owner'})
        self.assertEqual(self.status(),'pending');self.assertFalse(self.requests)
    def test_completion_checks_all_posts_before_unlocking(self):
        self.stage();self.transfer();self.cfg=self.primary_cfg
        self.proofs[7]={'vip_import_protocol':1,'local_post':7,'site_id':'SITE','generation':1,'enabled':True,'pending':1,'legacy':0}
        with self.assertRaises(WalletConflict):migration.finish({'login':'owner'},'COMPLETE VIP MIGRATION SITE SITE')
        self.assertTrue(migration.gate_locked(self.primary));self.proofs.clear();migration.finish({'login':'owner'},'COMPLETE VIP MIGRATION SITE SITE');self.assertFalse(migration.gate_locked(self.primary));self.assert_replica()
    def test_unknown_site_proof_blocks_first_grant(self):
        self.proofs[7]={'vip_import_protocol':1,'local_post':7,'site_id':'WRONG','generation':1,'enabled':True,'pending':0,'legacy':0}
        with self.assertRaises(WalletConflict):migration.guard_grant(self.primary,self.primary_cfg)
    def test_virtual_recovery_moves_to_vip_visit_only(self):
        session=self.local.execute("INSERT INTO wash_sessions(card_uid,source,status,ended_at,finished_at,final_credit_sum,metadata) VALUES('ABCD','vip','ended',now(),now(),1000,'{\"free_pause_remaining\":10}') RETURNING id").fetchone()['id']
        self.local.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason) VALUES(%s,1000,'power')",(session,));self.local.commit();self.stage();self.transfer()
        state=self.primary.inspect('ABCD')['state'];self.assertEqual(state['wallet_sum'],0);self.assertEqual(state['service_configuration']['vip_import_visits'][0]['remaining_sum'],1000)
        self.assertEqual(self.local.execute('SELECT status FROM recovery_credits').fetchone()['status'],'cancelled')
        result=self.wallet.execute('resume','ABCD',{'action':'grant_vip','post_no':7,'assignment_id':'a','visit_id':'v'},WalletPolicy())
        self.assertTrue(result['result']['continued']);self.assertEqual((result['result']['balance_sum'],result['result']['pause_millis']),(1000,10000));self.assert_replica()
    def test_mixed_legacy_vip_requires_reconciliation(self):
        self.local.execute("INSERT INTO wash_sessions(card_uid,source,status,ended_at,paid_sum) VALUES('ABCD','mixed','ended',now(),1000)");self.local.commit()
        with self.assertRaises(WalletConflict):self.stage()
        self.assertTrue(self.local.execute('SELECT enabled FROM rfid_cards').fetchone()['enabled'])
    def test_profile_conflict_keeps_pending_source(self):
        self.wallet.execute('profiles',wallet_registry.PROFILES_UID,{'action':'configure_service','value':{'profiles':[{'id':1,'code':'VIP','name':'VIP','enabled':True,'grant_seconds':120,'max_uses_per_day':5}]}},WalletPolicy());self.stage()
        with self.assertRaises(WalletConflict):self.transfer()
        self.assertEqual(self.status(),'pending');self.assertIsNone(self.primary.inspect('ABCD'))
    def test_completed_gate_removes_offline_post_dependency(self):
        self.wallet.execute('complete',migration.GATE_UID,{'action':'configure_service','value':{'complete':True}},WalletPolicy())
        with patch.object(migration,'rpc',side_effect=WalletUnavailable('offline')):migration.guard_grant(self.primary,self.primary_cfg)

    def legacy_virtual_session(self):
        session=self.local.execute("INSERT INTO wash_sessions(card_uid,source,status,ended_at,paid_sum) VALUES('ABCD','vip','ended',now(),15000) RETURNING id").fetchone()['id']
        self.local.execute("INSERT INTO payments(wash_session_id,provider,amount_sum,raw_payload) VALUES(%s,'vip',15000,'{\"conversion\":\"water_tariff\"}')",(session,))
        self.local.execute("INSERT INTO rfid_card_ledger(card_uid,wash_session_id,direction,reason,amount_sum) VALUES('ABCD',%s,'grant','vip_grant',15000)",(session,))
        self.local.commit();return session
    def test_real_legacy_virtual_grant_is_not_money(self):
        self.legacy_virtual_session();self.stage();self.transfer();self.assert_replica()
        self.assertEqual(self.primary.inspect('ABCD')['state']['wallet_sum'],0)
    def test_unexplained_paid_sum_stays_blocked(self):
        self.local.execute("INSERT INTO wash_sessions(card_uid,source,status,ended_at,paid_sum) VALUES('ABCD','vip','ended',now(),15000)");self.local.commit()
        with self.assertRaises(WalletConflict):self.stage()
        self.assertTrue(self.local.execute('SELECT enabled FROM rfid_cards').fetchone()['enabled'])
    def test_real_payment_in_mislabeled_vip_stays_blocked(self):
        session=self.legacy_virtual_session()
        self.local.execute("INSERT INTO payments(wash_session_id,provider,amount_sum) VALUES(%s,'cash',1000)",(session,));self.local.commit()
        with self.assertRaises(WalletConflict):self.stage()
    def test_mismatched_grant_proof_stays_blocked(self):
        session=self.legacy_virtual_session()
        self.local.execute("UPDATE rfid_card_ledger SET amount_sum=14000 WHERE wash_session_id=%s",(session,));self.local.commit()
        with self.assertRaises(WalletConflict):self.stage()
