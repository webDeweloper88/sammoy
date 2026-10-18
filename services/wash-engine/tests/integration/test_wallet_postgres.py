"""Disposable database only: durable transfers, restarts and concurrent requests."""
import os
from dataclasses import asdict
import threading
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from app.wallet_domain import WalletConflict, WalletPolicy
from app.wallet_store import WALLET_SCHEMA_SQL, WalletStore


@unittest.skipUnless(os.environ.get('WALLET_TEST_DSN'), 'Disposable PostgreSQL required')
class WalletPostgresTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['WALLET_TEST_DSN']
        self.schema='wallet_'+uuid4().hex
        self.conn=psycopg.connect(self.dsn,autocommit=True,row_factory=dict_row)
        if self.conn.info.dbname!='wallet_test':
            self.conn.close();raise RuntimeError('Refusing non-test database')
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        self.conn.execute(WALLET_SCHEMA_SQL)
        self.store=WalletStore(self.conn,'site-A');self.policy=WalletPolicy()

    def tearDown(self):
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.conn.close()

    def prepare(self, operation='opening', uid='CARD', **command):
        return self.store.prepare(operation,uid,command,self.policy)

    def opening(self):
        self.prepare(action='import_opening',amount_sum=35000)
        self.store.commit_prepared('opening')

    def connection(self):
        conn=psycopg.connect(self.dsn,autocommit=True,row_factory=dict_row)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        return conn

    def test_prepare_is_durable_but_not_spendable_after_restart(self):
        first=self.prepare(action='import_opening',amount_sum=35000)
        self.assertEqual(first['status'],'prepared')
        card=self.store.inspect('CARD');self.assertEqual(card['state']['wallet_sum'],0)
        self.assertFalse(card['available'])
        self.conn.close();self.conn=self.connection();self.store=WalletStore(self.conn,'site-A')
        retry=self.prepare(action='import_opening',amount_sum=35000)
        self.assertEqual(first,retry)
        committed=self.store.commit_prepared('opening');self.assertEqual(committed['status'],'committed')
        self.assertEqual(self.store.inspect('CARD')['state']['wallet_sum'],35000)
        self.assertEqual(committed,self.store.commit_prepared('opening'))

    def test_operation_id_content_and_card_cannot_be_reused(self):
        self.opening()
        for uid,amount in [('CARD',40000),('OTHER',35000)]:
            with self.assertRaises(WalletConflict):self.prepare(uid=uid,action='import_opening',amount_sum=amount)
        self.assertIsNone(self.store.inspect('OTHER'))

    def test_unresolved_transfer_blocks_later_commands(self):
        self.opening()
        self.prepare('load',action='reserve_load',post_no=2,assignment_id='a',visit_id='v')
        with self.assertRaises(WalletConflict):self.prepare('competing',action='reserve_load',post_no=7,assignment_id='b',visit_id='v')
        self.store.commit_prepared('load')
        self.assertEqual(self.store.inspect('CARD')['state']['assignment']['status'],'reserved')
        with self.assertRaises(WalletConflict):self.prepare('spend',action='spend',post_no=2,assignment_id='a',amount_sum=1)

    def test_site_isolation(self):
        self.opening()
        other=WalletStore(self.conn,'site-B')
        other.prepare('opening','CARD',{'action':'import_opening','amount_sum':5000},self.policy)
        other.commit_prepared('opening')
        self.assertEqual(other.inspect('CARD')['state']['wallet_sum'],5000)
        self.assertEqual(self.store.inspect('CARD')['state']['wallet_sum'],35000)

    def test_concurrent_loads_only_one_reservation(self):
        self.opening();barrier=threading.Barrier(2);results=[]
        def load(post):
            with self.connection() as conn:
                store=WalletStore(conn,'site-A');barrier.wait()
                try:
                    store.prepare('load-'+str(post),'CARD',{'action':'reserve_load','post_no':post,'assignment_id':str(post),'visit_id':'v'},self.policy)
                    results.append('prepared')
                except WalletConflict:results.append('blocked')
        threads=[threading.Thread(target=load,args=(post,)) for post in (2,7)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=10);self.assertFalse(t.is_alive())
        self.assertCountEqual(results,['prepared','blocked'])

    def test_bad_command_rolls_back_new_card_creation(self):
        with self.assertRaises(WalletConflict):self.prepare(action='import_opening',amount_sum=-1)
        self.assertIsNone(self.store.inspect('CARD'))
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM shared_wallet_operations').fetchone()['n'],0)

    def test_receipts_are_compact_global_and_deduplicated_across_operations(self):
        command={'action':'wallet_credit','post_no':2,'receipt_id':'post:2:payment:1','source':'cash','amount_sum':1000}
        for operation in ('first','retry-different-operation'):
            self.prepare(operation,**command);self.store.commit_prepared(operation)
        card=self.store.inspect('CARD')['state']
        self.assertEqual(card['wallet_sum'],1000);self.assertEqual(card['funding_receipts'],{})
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM shared_wallet_funding_receipts').fetchone()['n'],1)
        with self.assertRaises(WalletConflict):self.prepare('wrong-card',uid='OTHER',**command)
        with self.assertRaises(WalletConflict):self.prepare('wrong-amount',**{**command,'amount_sum':2000})


    def test_owner_vip_registry_reads_real_postgres_day_and_usage_without_writes(self):
        from app.wallet_registry import registry_payload
        self.assertEqual(registry_payload(self.store)['cards'],[])
        profile={'id':1,'code':'VIP','name':'VIP test','grant_seconds':600,'max_uses_per_day':2,'enabled':True}
        self.prepare('profiles',uid='@vip-profiles',action='configure_service',value={'profiles':[profile]})
        self.store.commit_prepared('profiles')
        self.prepare('vip',action='configure_vip',profile=profile)
        self.store.commit_prepared('vip')
        self.prepare('grant',action='grant_vip',post_no=2,assignment_id='assignment',visit_id='visit')
        self.store.commit_prepared('grant')
        before=(self.store.digest(),self.store.state_digest())
        payload=registry_payload(self.store)
        self.assertEqual(payload['profiles'],[profile])
        self.assertEqual(len(payload['cards']),1)
        card=payload['cards'][0]
        self.assertEqual(card['uid'],'CARD')
        self.assertEqual(card['uses_today'],1)
        self.assertEqual(card['active_post'],2)
        self.assertEqual(card['balance_sum'],0)
        self.assertEqual(card['usage_day'],self.conn.execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'Asia/Tashkent','YYYY-MM-DD') AS value").fetchone()['value'])
        self.assertEqual((self.store.digest(),self.store.state_digest()),before)
