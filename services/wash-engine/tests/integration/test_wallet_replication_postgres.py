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

    def typed(self,op,action,kind='wash',**kw):
        return self.coordinator.execute(op,'CARD',{'wallet_protocol':2,'device_type':kind,'action':action,**kw},WalletPolicy(bonus_mode='separate'))

    def test_device_wallet_migration_and_two_types_are_durable_on_both_nodes(self):
        self.opening()
        self.typed('migrate','migrate_device_wallet')
        self.typed('bonus','wallet_credit',source='cash',receipt_id='bonus-receipt',amount_sum=10000,bonus_sum=1000,bonus_domain='wash')
        r=self.typed('fog-load','reserve_load','dry_fog',post_no=2,assignment_id='fog',visit_id='visit')
        self.assertEqual(r['result']['balance_sum'],45000)
        self.typed('fog-accept','accept_load','dry_fog',post_no=2,assignment_id='fog')
        self.typed('fog-check','checkpoint','dry_fog',post_no=2,assignment_id='fog',remaining_sum=40000,remaining_bonus_sum=0,pause_millis=230000)
        self.typed('fog-prepare','prepare_return','dry_fog',post_no=2,assignment_id='fog')
        self.typed('fog-return','complete_return','dry_fog',post_no=2,assignment_id='fog')
        r=self.typed('wash-load','reserve_load',post_no=1,assignment_id='wash',visit_id='ignored-new-visit')
        self.assertEqual(r['result']['balance_sum'],41000);self.assertEqual(r['result']['bonus_sum'],1000)
        self.assertEqual(r['result']['pause_millis'],60000)
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))
        state=self.primary.inspect('CARD')['state']
        self.assertEqual(state['device_wallet']['pause_by_type']['dry_fog'],230000)
        self.assertEqual(state['spent_sum'],5000)
        self.assertEqual(self.primary.state_digest(),self.standby.state_digest())

    def test_typed_commit_reply_loss_retry_does_not_duplicate_domain_bonus(self):
        self.opening();self.typed('migrate','migrate_device_wallet')
        def lost(envelope):self.receiver.commit(envelope);raise WalletUnavailable('reply lost')
        self.coordinator.remote_commit=lost
        with self.assertRaises(WalletUnavailable):
            self.typed('fog-credit','wallet_credit','dry_fog',source='click',receipt_id='click:typed',amount_sum=10000,bonus_sum=1000,bonus_domain='dry_fog')
        self.coordinator.remote_commit=self.receiver.commit
        for _ in range(2):self.typed('fog-credit','wallet_credit','dry_fog',source='click',receipt_id='click:typed',amount_sum=10000,bonus_sum=1000,bonus_domain='dry_fog')
        state=self.primary.inspect('CARD')['state']
        self.assertEqual(state['wallet_sum'],46000);self.assertEqual(state['device_wallet']['wallet_bonus']['dry_fog'],1000)
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))
        # A new operation ID with the same receipt is also safe after restart.
        self.primary=WalletStore(self.nodes[0][0],'SITE');self.coordinator.store=self.primary
        self.typed('fog-credit-new-id','wallet_credit','dry_fog',source='click',receipt_id='click:typed',amount_sum=10000,bonus_sum=1000,bonus_domain='dry_fog')
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],46000)

    def test_old_replica_cannot_ack_typed_snapshot_and_primary_does_not_commit(self):
        self.opening()
        def old_node(envelope):
            if 'device_wallet' in envelope['payload']['proposed_state']:raise WalletUnavailable('Old node cannot parse typed wallet')
            return self.receiver.stage(envelope)
        self.coordinator.remote_stage=old_node
        with self.assertRaises(WalletUnavailable):self.typed('migrate','migrate_device_wallet')
        self.assertFalse(self.primary.inspect('CARD')['available'])
        self.assertNotIn('device_wallet',self.primary.inspect('CARD')['state'])
        self.assertEqual(self.primary.inspect('CARD')['state']['wallet_sum'],35000)
        self.coordinator.remote_stage=self.receiver.stage;self.typed('migrate','migrate_device_wallet')
        self.assertEqual(self.primary.inspect('CARD'),self.standby.inspect('CARD'))
        with self.assertRaises(WalletConflict):
            self.coordinator.execute('old-post','CARD',{'action':'reserve_load','post_no':1,'assignment_id':'a','visit_id':'v'},self.policy)
