"""Three independent node schemas on a disposable PostgreSQL, real signed RPCs."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app import wallet_api as a, wallet_management as m
from app.wallet_store import WALLET_SCHEMA_SQL, WalletStore
from app.wallet_domain import WalletConflict, WalletPolicy
from app.wallet_replication import Authority, ReplicaReceiver, ReplicatedWallet, WalletUnavailable


@unittest.skipUnless(os.environ.get('WALLET_TEST_DSN'),'Disposable PostgreSQL required')
class ManagementPostgresTests(unittest.TestCase):
    def setUp(self):
        self.current=1;self.nodes={};self.drop=None
        for post in (1,2,3):
            conn=psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True,row_factory=dict_row)
            if conn.info.dbname!='wallet_test':raise RuntimeError('Refusing non-test database')
            schema='membership_'+uuid4().hex
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            conn.execute(WALLET_SCHEMA_SQL)
            conn.execute('CREATE TABLE app_settings(setting_key text PRIMARY KEY,setting_value jsonb NOT NULL,updated_at timestamptz DEFAULT now())')
            conn.execute('CREATE TABLE system_events(level text,event_type text,source text,message text,context jsonb)')
            conn.execute('CREATE TABLE rfid_cards(balance_sum bigint,card_type text)')
            cfg={'enabled':True,'primary_post':1,'standby_post':3 if post==3 else 2,'generation':1 if post==3 else 3,
                 'single_node':False,'standby_ready':post!=3,'visit_timeout_minutes':30,
                 'peer_urls':{str(p):f'http://10.0.0.{p}' for p in (1,2,3)}}
            conn.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('shared_wallet',%s)",(Jsonb(cfg),))
            self.nodes[post]=(conn,schema)
        self.patches=[patch.object(a,'configuration',side_effect=self.configuration),
                      patch.object(a,'store_context',side_effect=self.store_context),patch.object(a,'db',side_effect=self.db),
                      patch.object(a,'rpc',side_effect=self.rpc),patch.object(a,'identity',return_value={'site_token':'isolated-management-test-key'}),
                      patch.object(m,'idle'),patch.object(m,'worker_lock',threading.Lock())]
        for p in self.patches:p.start()
        one=WalletStore(self.nodes[1][0],'SITE');two=WalletStore(self.nodes[2][0],'SITE')
        receiver=ReplicaReceiver(two,Authority('SITE',2,1,2,3))
        wallet=ReplicatedWallet(one,Authority('SITE',1,1,2,3),receiver.stage,receiver.commit)
        wallet.execute('opening','CARD',{'action':'import_opening','amount_sum':35000},WalletPolicy())
        wallet.execute('policy','@device-policy',{'action':'configure_service','value':{'test':'preserve configuration'}},WalletPolicy())
        self.original=deepcopy(one.inspect('CARD'))

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        for conn,schema in self.nodes.values():
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));conn.close()

    def configuration(self):
        conn,_=self.nodes[self.current]
        value=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='shared_wallet'").fetchone()['setting_value']
        return {**value,'site_id':'SITE','local_post':self.current}

    @contextmanager
    def db(self):yield self.nodes[self.current][0]

    @contextmanager
    def store_context(self,cfg,allow_management=False):
        conn,_=self.nodes[self.current]
        # Physical nodes have distinct PG lock namespaces; schemas share one
        # server here, so include the test-node ID to represent that isolation.
        key=f'wallet:SITE:{self.current}'
        conn.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(key,))
        try:
            actual=self.configuration()
            if m.roles(actual)!=m.roles(cfg):raise WalletConflict('Stale authority')
            if actual.get('management_pending') and not allow_management:raise WalletUnavailable('paused')
            yield WalletStore(conn,'SITE')
        finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(key,))

    def rpc(self,cfg,post,action,payload):
        if str(post) not in cfg['peer_urls']:raise WalletUnavailable('Peer address or site key is missing')
        body={'site_id':'SITE','sender_post':cfg['local_post'],'timestamp':int(time.time()),'payload':deepcopy(payload)}
        path='/api/wallet/internal/'+action
        signature=a.signature('isolated-management-test-key',path,body)
        previous=self.current;self.current=post
        try:response=a.internal(action,body,x_wallet_signature=signature,x_real_ip=f'10.0.0.{previous}')
        finally:self.current=previous
        result=json.loads(response.body)
        self.assertEqual(response.headers['X-Wallet-Signature'],a.signature('isolated-management-test-key',path,result))
        if response.status_code!=200:raise WalletConflict(result.get('detail','RPC failed'))
        if self.drop==action:self.drop=None;raise WalletUnavailable('reply lost after durable action')
        return result

    def start(self,kind='replace_standby'):
        target=3 if kind=='replace_standby' else 2
        selection=m.Selection(kind=kind,target_post=target,target_url=f'http://10.0.0.{target}')
        cfg=self.configuration();plan=m.preflight(cfg,selection)
        job={**selection.model_dump(),'request_id':str(uuid4()),'before':plan['before'],'after':plan['after'],
             'peer_urls':plan['peer_urls'],'actor':'owner','stage':'checking','error':None}
        with self.store_context(cfg):m.persist(cfg,job,'test_started')
        return job

    def run_job(self,job):
        self.assertTrue(m.worker_lock.acquire(False));m.run_job(job['request_id'])

    def assert_complete(self,job):
        cfg=self.configuration()
        self.assertIsNone(cfg.get('management_pending'),cfg.get('management_pending'))
        self.assertEqual(m.roles(cfg),job['after'])
        for post in (1,job['target_post']):
            store=WalletStore(self.nodes[post][0],'SITE')
            self.assertEqual(store.inspect('CARD'),self.original)
            self.assertEqual(store.diagnostics()['pending_count'],0)
        self.assertTrue(m.same_proof(WalletStore(self.nodes[1][0],'SITE').diagnostics(),WalletStore(self.nodes[job['target_post']][0],'SITE').diagnostics()))

    def test_replaces_reserve_and_copies_real_journal_balances_and_configuration(self):
        job=self.start();self.run_job(job);self.assert_complete(job)
        self.current=2;old=self.configuration()
        self.assertFalse(old['standby_ready']);self.assertEqual(old['standby_post'],3)

    def test_replacement_adds_previously_unknown_standby_address(self):
        cfg=self.configuration();del cfg['peer_urls']['3']
        a.persist_configuration(cfg,{'login':'owner'},'test_unknown_target_address')
        job=self.start();self.run_job(job);self.assert_complete(job)

    def test_lost_copy_commit_ack_resumes_without_double_money(self):
        job=self.start();self.drop='replica-commit';self.run_job(job)
        self.assertTrue(self.configuration()['management_pending']['error'])
        self.run_job(job);self.assert_complete(job)

    def test_lost_activation_ack_resumes_from_persisted_roles(self):
        job=self.start();self.drop='management-activate';self.run_job(job)
        self.assertEqual(self.configuration()['management_pending']['stage'],'activating')
        self.run_job(job);self.assert_complete(job)

    def test_handover_preserves_money_and_allows_two_node_writes_afterward(self):
        job=self.start('handover');self.run_job(job);self.assert_complete(job)
        self.current=2;cfg=self.configuration()
        with self.store_context(cfg) as store:
            a.coordinator(store,cfg).execute('next','CARD',{'action':'reserve_load','post_no':3,'assignment_id':'after-handover','visit_id':'v'},WalletPolicy())
        self.assertEqual(WalletStore(self.nodes[1][0],'SITE').inspect('CARD'),WalletStore(self.nodes[2][0],'SITE').inspect('CARD'))

    def test_stale_metadata_cannot_clear_in_progress_change(self):
        stale=self.configuration();self.start()
        with self.assertRaises(WalletConflict):a.persist_configuration(stale,{'login':'stale'},'stale_metadata')
        self.assertTrue(self.configuration()['management_pending'])

    def test_conflicting_target_history_is_not_deleted_or_activated(self):
        store=WalletStore(self.nodes[3][0],'SITE')
        store.prepare('other','OTHER',{'action':'import_opening','amount_sum':1},WalletPolicy());store.commit_prepared('other')
        job=self.start();self.run_job(job)
        self.assertTrue(self.configuration()['management_pending']['error'])
        self.assertEqual(store.inspect('OTHER')['state']['wallet_sum'],1)
        self.current=3;self.assertFalse(self.configuration()['standby_ready'])

    def test_cancel_before_switch_restores_roles_and_keeps_copied_data(self):
        job=self.start();self.drop='replica-commit';self.run_job(job)
        copied=WalletStore(self.nodes[3][0],'SITE').inspect('CARD')
        with patch.object(m,'fresh'):
            m.cancel(m.Resume(request_id=job['request_id']),{'login':'owner'},None)
        self.assertEqual(m.roles(self.configuration()),job['before'])
        self.assertIsNone(self.configuration().get('management_pending'))
        self.assertTrue(self.configuration()['standby_ready'])
        with self.assertRaises(WalletConflict):a.persist_configuration({**self.configuration(),'management_pending':{**job,'stage':'checking'}},{'login':'stale'},'reopen_cancelled')
        self.current=3
        self.assertEqual(self.configuration()['generation'],1)
        self.assertIsNone(self.configuration().get('management_pending'))
        self.assertEqual(WalletStore(self.nodes[3][0],'SITE').inspect('CARD'),copied)
        self.current=1;cfg=self.configuration()
        with self.store_context(cfg) as store:
            a.coordinator(store,cfg).execute('after-cancel','CARD',{'action':'reserve_load','post_no':3,'assignment_id':'cancel-kept','visit_id':'v'},WalletPolicy())
        self.assertEqual(WalletStore(self.nodes[1][0],'SITE').inspect('CARD'),WalletStore(self.nodes[2][0],'SITE').inspect('CARD'))

    def test_cancel_is_rejected_after_role_switch_boundary(self):
        job=self.start();job['stage']='retiring';cfg=self.configuration();m.persist(cfg,job,'test_boundary')
        from fastapi import HTTPException
        with patch.object(m,'fresh'),self.assertRaises(HTTPException):
            m.cancel(m.Resume(request_id=job['request_id']),{'login':'owner'},None)
        self.assertEqual(self.configuration()['management_pending']['stage'],'retiring')

    def test_finished_job_cannot_be_reopened_by_stale_target_metadata(self):
        job=self.start();self.drop='management-activate';self.run_job(job)
        self.current=3;cfg=self.configuration()
        self.assertIsNone(cfg.get('management_pending'))
        stale={**cfg,'management_pending':{**job,'stage':'prepared'},'management_last':None}
        with self.assertRaises(WalletConflict):a.persist_configuration(stale,{'login':'stale'},'stale_prepare')

    def test_fresh_activated_candidate_can_join_without_manual_wallet_roles(self):
        self.current=3;cfg=self.configuration();cfg.update(enabled=False,peer_urls={},standby_post=None,standby_ready=False)
        self.nodes[3][0].execute("UPDATE app_settings SET setting_value=%s WHERE setting_key='shared_wallet'",(Jsonb(cfg),))
        self.current=1
        with patch('app.main.get_commissioning_state',return_value={'complete':False}),patch('app.main.apply_license_to_runtime',return_value={'locked':False}):
            job=self.start();self.run_job(job);self.assert_complete(job)
        self.current=3;self.assertTrue(self.configuration()['enabled'])

    def test_bootstrap_does_not_claim_local_money_or_vip_cards(self):
        for amount,card_type in ((1,'customer'),(0,'vip')):
            self.current=3;cfg=self.configuration();cfg.update(enabled=False,peer_urls={},standby_post=None,standby_ready=False)
            conn=self.nodes[3][0];conn.execute("UPDATE app_settings SET setting_value=%s WHERE setting_key='shared_wallet'",(Jsonb(cfg),))
            conn.execute('DELETE FROM rfid_cards');conn.execute('INSERT INTO rfid_cards VALUES(%s,%s)',(amount,card_type))
            self.current=1
            with patch('app.main.get_commissioning_state',return_value={'complete':False}),patch('app.main.apply_license_to_runtime',return_value={'locked':False}),self.assertRaises(WalletConflict):self.start()
            self.assertIsNone(self.configuration().get('management_pending'))
            self.assertEqual(conn.execute('SELECT balance_sum FROM rfid_cards').fetchone()['balance_sum'],amount)

    def test_same_number_attachment_skips_retiring_the_new_reserve(self):
        self.current=1;cfg=self.configuration();cfg['standby_ready']=False
        self.nodes[1][0].execute("UPDATE app_settings SET setting_value=%s WHERE setting_key='shared_wallet'",(Jsonb(cfg),))
        self.current=2;cfg=self.configuration();cfg.update(enabled=False,standby_ready=False,peer_urls={},standby_post=None)
        self.nodes[2][0].execute("UPDATE app_settings SET setting_value=%s WHERE setting_key='shared_wallet'",(Jsonb(cfg),))
        self.current=1
        selection=m.Selection(kind='replace_standby',target_post=2,target_url='http://10.0.0.2')
        with patch('app.main.get_commissioning_state',return_value={'complete':False}),patch('app.main.apply_license_to_runtime',return_value={'locked':False}):
            cfg=self.configuration();plan=m.preflight(cfg,selection)
            job={**selection.model_dump(),'request_id':str(uuid4()),'before':plan['before'],'after':plan['after'],'peer_urls':plan['peer_urls'],'actor':'owner','stage':'checking','error':None}
            m.persist(cfg,job,'test_attach_started');self.run_job(job);self.assert_complete(job)

    def test_management_is_serialized_between_database_sessions(self):
        with psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True) as other:
            other.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',('wallet-management:SITE',))
            try:
                with self.assertRaises(m.ManagementBusy):
                    with m.distributed():self.fail('Concurrent manager acquired the lock')
            finally:other.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',('wallet-management:SITE',))

    def test_rejoin_after_fenced_failover_can_supersede_a_lost_activation_ack(self):
        job=self.start();self.drop='management-activate';self.run_job(job)
        self.assertEqual(self.configuration()['management_pending']['stage'],'activating')
        self.current=3
        a.promote(a.PromoteRequest(old_primary_fenced=True,single_node_confirmed=True,confirmation='PROMOTE POST 3'),{'login':'owner'})
        a.synchronize({'login':'owner'})
        self.assertEqual(self.configuration()['primary_post'],3)
        self.assertFalse(self.configuration()['single_node'])
        self.current=1;cfg=self.configuration()
        self.assertIsNone(cfg.get('management_pending'))
        self.assertEqual(cfg['management_last']['stage'],'superseded')
        self.assertEqual(cfg['primary_post'],3)
        self.assertTrue(cfg['standby_ready'])
        self.assertEqual(WalletStore(self.nodes[1][0],'SITE').inspect('CARD'),WalletStore(self.nodes[3][0],'SITE').inspect('CARD'))

    def test_destructive_reset_is_refused_while_roles_are_changing(self):
        from app.system_reset import check_ready
        self.start()
        with self.assertRaises(RuntimeError):check_ready(self.nodes[1][0],'full')
        self.assertTrue(self.configuration()['management_pending'])
        self.assertEqual(WalletStore(self.nodes[1][0],'SITE').inspect('CARD'),self.original)
