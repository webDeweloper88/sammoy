"""Two real HTTP processes, separate disposable PostgreSQL databases."""
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import unittest
import httpx
import psycopg
from psycopg import sql
from app.config import settings
from app.wallet_api import signature


@unittest.skipUnless(os.environ.get('WALLET_HTTP_TEST')=='1','Explicit disposable HTTP test required')
class WalletHttpTests(unittest.TestCase):
    def setUp(self):
        self.databases={post:'wallet_http_test_'+uuid4().hex+'_'+str(post) for post in (1,7)}
        self.processes={};self.http=httpx.Client(timeout=15,trust_env=False)
        with psycopg.connect(settings.database_url,autocommit=True) as conn:
            for name in self.databases.values():conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        self.start(7);self.start(1)

    def tearDown(self):
        for process in self.processes.values():
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        self.http.close()
        with psycopg.connect(settings.database_url,autocommit=True) as conn:
            for name in self.databases.values():
                if not name.startswith('wallet_http_test_'):raise RuntimeError('Refusing DB drop')
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def start(self,post):
        env={**os.environ,'WASH_ENGINE_POSTGRES_DB':self.databases[post],'WALLET_TEST_POST':str(post)}
        path=Path(__file__).with_name('wallet_http_node.py')
        p=subprocess.Popen([sys.executable,str(path)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        self.processes[post]=p
        for _ in range(100):
            if p.poll() is not None:raise RuntimeError('HTTP fixture failed: '+p.stderr.read()[-2000:])
            try:
                r=self.http.get(self.url(post)+'/api/owner/wallet',headers={'Authorization':'Bearer fixture-owner'})
                if r.status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise RuntimeError('HTTP fixture startup timed out')

    def url(self,post):return 'http://127.0.0.1:'+str(18591 if post==1 else 18597)
    def owner(self,post,action,payload=None):
        r=self.http.post(self.url(post)+'/api/owner/wallet/'+action,json=payload or {},headers={'Authorization':'Bearer fixture-owner'})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def internal(self,post,action,payload,sender=2):
        path='/api/wallet/internal/'+action;body={'site_id':'HTTP_TEST','sender_post':sender,'timestamp':int(time.time()),'payload':payload}
        r=self.http.post(self.url(post)+path,json=body,headers={'X-Wallet-Signature':signature('http-test-site-key',path,body),'X-Real-IP':'127.0.0.1'})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def execute(self,post,op,command):
        return self.internal(post,'execute',{'uid':'7C212602','operation_id':op,'command':{'post_no':2,**command}})

    def test_sync_failover_rejoin_and_current_authority_persistence(self):
        self.owner(1,'synchronize')
        self.execute(1,'load',{'action':'reserve_load','assignment_id':'a','visit_id':'v'})
        self.execute(1,'accept',{'action':'accept_load','assignment_id':'a'})
        self.execute(1,'checkpoint',{'action':'checkpoint','assignment_id':'a','remaining_sum':33000,'pause_millis':10000,
             'funding':[{'id':'cash:one','source':'cash','amount_sum':10000}]})
        self.execute(1,'prepare',{'action':'prepare_return','assignment_id':'a'})
        self.execute(1,'return',{'action':'complete_return','assignment_id':'a'})
        self.assertEqual(self.internal(1,'inspect',{'uid':'7C212602'})['card']['state']['wallet_sum'],33000)
        self.processes[1].terminate();self.processes[1].wait(timeout=5)
        promoted=self.owner(7,'promote',{'confirmation':'PROMOTE POST 7','old_primary_fenced':True,'single_node_confirmed':True})
        self.assertEqual(promoted['configuration']['primary_post'],7)
        self.assertTrue(promoted['configuration']['single_node'])
        self.execute(7,'new-load',{'action':'reserve_load','assignment_id':'b','visit_id':'ignored'})
        self.start(1)
        # An old primary cannot obtain a standby acknowledgement from the
        # promoted node, so it cannot complete a competing transfer.
        path='/api/wallet/internal/execute';body={'site_id':'HTTP_TEST','sender_post':2,'timestamp':int(time.time()),
             'payload':{'uid':'7C212602','operation_id':'stale-load','command':{'action':'reserve_load','post_no':2,'assignment_id':'stale','visit_id':'stale'}}}
        r=self.http.post(self.url(1)+path,json=body,headers={'X-Wallet-Signature':signature('http-test-site-key',path,body)})
        self.assertNotEqual(r.status_code,200)
        self.owner(7,'synchronize')
        status=self.http.get(self.url(1)+'/api/owner/wallet',headers={'Authorization':'Bearer fixture-owner'}).json()
        self.assertEqual(status['role'],'standby');self.assertTrue(status['configuration']['standby_ready'])
        self.assertEqual(status['configuration']['primary_post'],7)
        self.execute(7,'new-accept',{'action':'accept_load','assignment_id':'b'})
        self.assertEqual(self.internal(7,'inspect',{'uid':'7C212602'})['card']['state']['assignment']['balance_sum'],33000)
        self.owner(7,'timeout',{'visit_timeout_minutes':45})
        secondary=self.http.get(self.url(1)+'/api/owner/wallet',headers={'Authorization':'Bearer fixture-owner'}).json()
        self.assertEqual(secondary['configuration']['visit_timeout_minutes'],45)
