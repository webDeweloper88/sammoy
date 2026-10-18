import os
import unittest
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from app.wallet_store import WALLET_SCHEMA_SQL, WalletStore
from app.wallet_domain import WalletConflict, WalletPolicy
from app.wallet_replication import Authority, ReplicaReceiver, ReplicatedWallet, WalletUnavailable, promotion_plan


@unittest.skipUnless(os.environ.get('WALLET_TEST_DSN'),'Disposable PostgreSQL required')
class WalletReplicationTests(unittest.TestCase):
    def setUp(self):
        self.nodes=[];self.policy=WalletPolicy()
        for _ in range(2):
            conn=psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True,row_factory=dict_row)
            if conn.info.dbname!='wallet_test':raise RuntimeError('Refusing live database')
            schema='replica_'+uuid4().hex
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            conn.execute(WALLET_SCHEMA_SQL);self.nodes.append((conn,schema))
        self.primary=WalletStore(self.nodes[0][0],'SITE')
        self.standby=WalletStore(self.nodes[1][0],'SITE')
        self.authority=Authority('SITE',1,1,7)
        self.receiver=ReplicaReceiver(self.standby,Authority('SITE',7,1,7))
        self.coordinator=ReplicatedWallet(self.primary,self.authority,self.receiver.stage,self.receiver.commit)

    def tearDown(self):
        for conn,schema in self.nodes:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));conn.close()

    def opening(self):
        return self.coordinator.execute('opening','CARD',{'action':'import_opening','amount_sum':35000},self.policy)

    def test_success_is_durable_on_both_nodes(self):
        self.opening()
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))
        self.assertEqual(self.standby.inspect('CARD')['state']['wallet_sum'],35000)

    def test_lost_stage_response_keeps_primary_pending_and_retry_reconciles(self):
        def lost(envelope):self.receiver.stage(envelope);raise WalletUnavailable('lost response')
        self.coordinator.remote_stage=lost
        with self.assertRaises(WalletUnavailable):self.opening()
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],0)
        self.assertEqual(self.standby.inspect('CARD')['state']['wallet_sum'],0)
        self.coordinator.remote_stage=self.receiver.stage;self.opening()
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))

    def test_lost_commit_response_cannot_duplicate_funds(self):
        def lost(envelope):self.receiver.commit(envelope);raise WalletUnavailable('lost response')
        self.coordinator.remote_commit=lost
        with self.assertRaises(WalletUnavailable):self.opening()
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],0)
        self.assertEqual(self.standby.inspect('CARD')['state']['wallet_sum'],35000)
        self.coordinator.remote_commit=self.receiver.commit
        self.opening();self.opening()
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],35000)
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))

    def test_standby_down_never_falls_back_to_local_success(self):
        self.coordinator.remote_stage=lambda envelope:(_ for _ in ()).throw(WalletUnavailable('down'))
        with self.assertRaises(WalletUnavailable):self.opening()
        with self.assertRaises(WalletUnavailable):self.coordinator.execute('different','OTHER',{'action':'import_opening','amount_sum':1},self.policy)
        self.assertIsNone(self.standby.inspect('CARD'))

    def test_old_authority_rejected_after_manual_promotion(self):
        self.opening()
        promoted=promotion_plan(Authority('SITE',7,1,7),old_primary_fenced=True,single_node_confirmed=True)
        self.assertEqual((promoted.primary_post,promoted.standby_post,promoted.generation),(7,1,2))
        self.assertTrue(promoted.single_node)
        receiver=ReplicaReceiver(self.primary,Authority('SITE',1,7,1,2))
        with self.assertRaises(WalletConflict):receiver.stage(self.authority.envelope(self.standby.export_operation('opening')))
        with self.assertRaises(WalletUnavailable):ReplicatedWallet(self.primary,Authority('SITE',1,7,1,2),None,None).execute('x','CARD',{},self.policy)

    def test_promotion_never_inferred_from_timeout(self):
        for fence,single in [(False,True),(True,False),(False,False)]:
            with self.assertRaises(WalletConflict):promotion_plan(Authority('SITE',7,1,7),old_primary_fenced=fence,single_node_confirmed=single)

    def test_single_mode_then_old_primary_catches_up(self):
        self.opening()
        promoted=promotion_plan(Authority('SITE',7,1,7),old_primary_fenced=True,single_node_confirmed=True)
        solo=ReplicatedWallet(self.standby,promoted,None,None)
        solo.execute('load','CARD',{'action':'reserve_load','post_no':2,'assignment_id':'a','visit_id':'v'},self.policy)
        old=ReplicaReceiver(self.primary,Authority('SITE',1,7,1,2))
        replicated=ReplicatedWallet(self.standby,Authority('SITE',7,7,1,2),old.stage,old.commit)
        replicated.catch_up()
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))
        self.assertEqual(self.primary.inspect('CARD')['state']['assignment']['status'],'reserved')

    def test_conflicting_replica_cannot_overwrite_journal(self):
        self.opening();payload=self.primary.export_operation('opening')
        payload['proposed_state']['opening_sum']=999
        with self.assertRaises(WalletConflict):self.receiver.stage(self.authority.envelope(payload))
        self.assertEqual(self.standby.inspect('CARD')['state']['wallet_sum'],35000)

    def test_replica_rejects_revision_gap_and_wrong_site(self):
        self.opening();self.coordinator.execute('load','CARD',{'action':'reserve_load','post_no':2,'assignment_id':'a','visit_id':'v'},self.policy)
        payload=self.primary.export_operation('load');payload['site_id']='OTHER'
        with self.assertRaises(WalletConflict):self.receiver.stage(self.authority.envelope(payload))
