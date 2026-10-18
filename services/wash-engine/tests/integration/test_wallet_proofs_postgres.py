import os
import unittest
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
import time
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.wallet_store import WalletStore,WALLET_SCHEMA_SQL
from app.wallet_domain import WalletPolicy
from app.wallet_replication import Authority,ReplicaReceiver,ReplicatedWallet
from app import wallet_api

@unittest.skipUnless(os.getenv('WALLET_TEST_DSN'),'Disposable PostgreSQL required')
class WalletProofTests(unittest.TestCase):
    def setUp(self):
        self.nodes=[]
        for _ in range(2):
            conn=psycopg.connect(os.environ['WALLET_TEST_DSN'],autocommit=True,row_factory=dict_row)
            assert conn.info.dbname=='wallet_test'
            schema='proof_'+uuid4().hex;conn.execute('CREATE SCHEMA '+schema);conn.execute('SET search_path TO '+schema)
            conn.execute(WALLET_SCHEMA_SQL);self.nodes.append((conn,schema))
        self.primary=WalletStore(self.nodes[0][0],'SITE');self.standby=WalletStore(self.nodes[1][0],'SITE')
        self.authority=Authority('SITE',1,1,7)
        replica=ReplicaReceiver(self.standby,Authority('SITE',7,1,7))
        ReplicatedWallet(self.primary,self.authority,replica.stage,replica.commit).execute('open','CARD',{'action':'import_opening','amount_sum':35000},WalletPolicy())
    def tearDown(self):
        for conn,schema in self.nodes:conn.execute('DROP SCHEMA '+schema+' CASCADE');conn.close()
    def assert_tamper_detected(self):
        self.assertEqual(self.primary.digest(),self.standby.digest())
        self.assertNotEqual(self.primary.state_digest(),self.standby.state_digest())
    def corrupt_card(self):
        self.nodes[1][0].execute("UPDATE shared_wallet_cards SET state=jsonb_set(state,'{wallet_sum}','1') WHERE uid='CARD'")
    def test_materialized_card_tamper_is_visible_despite_matching_journals(self):
        self.assertEqual(self.primary.state_digest(),self.standby.state_digest());self.corrupt_card();self.assert_tamper_detected()
    def test_receipt_tamper_is_visible(self):
        for conn,_ in self.nodes:conn.execute("INSERT INTO shared_wallet_funding_receipts(site_id,receipt_id,uid,value) VALUES('SITE','receipt','CARD','{\"amount_sum\":1000}')")
        self.assertEqual(self.primary.state_digest(),self.standby.state_digest())
        self.nodes[1][0].execute("UPDATE shared_wallet_funding_receipts SET value='{\"amount_sum\":2000}'")
        self.assert_tamper_detected()
    def test_vip_daily_limit_tamper_is_visible(self):
        for conn,_ in self.nodes:conn.execute("INSERT INTO shared_wallet_vip_uses VALUES('SITE','CARD','2026-10-10',1)")
        self.assertEqual(self.primary.state_digest(),self.standby.state_digest())
        self.nodes[1][0].execute('UPDATE shared_wallet_vip_uses SET used=2');self.assert_tamper_detected()
    def test_pagination_includes_rows_after_first_page(self):
        for conn,_ in self.nodes:
            conn.execute("INSERT INTO shared_wallet_funding_receipts(site_id,receipt_id,uid,value) SELECT 'SITE',lpad(n::text,4,'0'),'CARD',jsonb_build_object('amount_sum',n) FROM generate_series(1,350) n")
        self.assertEqual(self.primary.state_digest(),self.standby.state_digest())
        self.nodes[1][0].execute("UPDATE shared_wallet_funding_receipts SET value='{}' WHERE receipt_id='0349'")
        self.assert_tamper_detected()
    def test_ready_check_rejects_materialized_corruption_and_clears_old_flag(self):
        self.corrupt_card()
        cfg={'enabled':True,'site_id':'SITE','local_post':7,'primary_post':1,'standby_post':7,'generation':1,'single_node':False,'standby_ready':True,'peer_urls':{'1':'http://10.0.0.1','7':'http://10.0.0.7'}}
        @contextmanager
        def store(cfg):yield self.standby
        app=FastAPI();app.include_router(wallet_api.router)
        path='/api/wallet/internal/replica-ready'
        body={'site_id':'SITE','sender_post':1,'timestamp':int(time.time()),'payload':self.authority.envelope({'proof_version':2,'digest':self.primary.digest(),'state_digest':self.primary.state_digest()})}
        with patch.object(wallet_api,'configuration',return_value=cfg),patch.object(wallet_api,'identity',return_value={'site_token':'test-secret'}),patch.object(wallet_api,'store_context',store),patch.object(wallet_api,'persist_configuration') as persist:
            response=TestClient(app).post(path,json=body,headers={'X-Wallet-Signature':wallet_api.signature('test-secret',path,body)})
        self.assertEqual(response.status_code,409);self.assertFalse(cfg['standby_ready']);persist.assert_called_once()
        from psycopg.types.json import Jsonb
        self.nodes[1][0].execute("UPDATE shared_wallet_cards SET state=%s WHERE uid='CARD'",(Jsonb(self.primary.inspect('CARD')['state']),))
        with patch.object(wallet_api,'configuration',return_value=cfg),patch.object(wallet_api,'identity',return_value={'site_token':'test-secret'}),patch.object(wallet_api,'store_context',store),patch.object(wallet_api,'persist_configuration'):
            response=TestClient(app).post(path,json=body,headers={'X-Wallet-Signature':wallet_api.signature('test-secret',path,body)})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['proof_version'],2)
        self.assertEqual(response.json()['state_digest'],self.primary.state_digest())
