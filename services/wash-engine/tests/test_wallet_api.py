import hashlib
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch,MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import current_user
from app import wallet_api as api


class WalletApiTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI();self.app.include_router(api.router);self.client=TestClient(self.app)
        self.cfg={'enabled':True,'site_id':'SITE','local_post':7,'primary_post':1,'standby_post':7,'generation':2,
                  'single_node':False,'standby_ready':True,'visit_timeout_minutes':30,'peer_urls':{'1':'http://10.0.0.1','2':'http://10.0.0.2','7':'http://10.0.0.7'}}
        self.patches=[patch.object(api,'configuration',return_value=self.cfg),patch.object(api,'identity',return_value={'site_token':'test-site-secret'})]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.app.dependency_overrides.clear()

    def call(self,action,payload,sender=1,stamp=None,secret='test-site-secret'):
        body={'site_id':'SITE','sender_post':sender,'timestamp':int(time.time()) if stamp is None else stamp,'payload':payload}
        path='/api/wallet/internal/'+action
        return self.client.post(path,json=body,headers={'X-Wallet-Signature':api.signature(secret,path,body)})

    def test_operator_call_uses_signed_sender_and_never_holds_wallet_lock(self):
        with patch.object(api,'authority'),patch('app.contact_api.setup_call',return_value={'ok':True,'status':'queued'}) as send,patch.object(api,'control_lock') as lock:
            result=self.call('operator-call',{'site_id':'SITE','post_no':2,'request_id':'11111111-1111-4111-8111-111111111111'},sender=2)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['status'],'queued')
            lock.__enter__.assert_not_called()
            send.reset_mock()
            self.assertEqual(self.call('operator-call',{'site_id':'SITE','post_no':7},sender=2).status_code,503)
            send.assert_not_called()

    def test_no_site_secret_or_bad_signature_cannot_read_or_write(self):
        with patch.object(api,'store_context') as store:
            self.assertEqual(self.call('status',{},secret='wrong').status_code,401)
            self.assertEqual(self.call('status',{},stamp=int(time.time())-61).status_code,401)
            self.assertEqual(self.call('status',{},sender=99).status_code,403)
            store.assert_not_called()

    def test_authenticated_status_response_is_signed_and_request_bound(self):
        response=self.call('status',{})
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['primary_post'],1)
        self.assertEqual(response.headers['X-Wallet-Signature'],api.signature('test-site-secret','/api/wallet/internal/status',data))
        self.assertEqual(len(data['request_digest']),64)

    def test_old_generation_cannot_stage_replica(self):
        @contextmanager
        def fake(cfg):
            store=MagicMock();store._operation.return_value=None;yield store
        with patch.object(api,'store_context',fake):
            response=self.call('replica-stage',{'site_id':'SITE','generation':1,'primary_post':1,'sender_post':1,'payload':{}})
        self.assertEqual(response.status_code,409)
        self.assertIn('Stale',response.json()['detail'])

    def test_post_cannot_impersonate_another_assignment(self):
        self.cfg['local_post']=1
        @contextmanager
        def fake(cfg):
            store=MagicMock();store._operation.return_value=None;yield store
        with patch.object(api,'store_context',fake),patch.object(api,'coordinator') as coordinator:
            response=self.call('execute',{'uid':'CARD','operation_id':'id','command':{'action':'reserve_load','post_no':7}},sender=2)
            self.assertEqual(response.status_code,409);coordinator.assert_not_called()

    def test_owner_and_installer_permissions_and_password_change(self):
        self.assertEqual(self.client.get('/api/owner/wallet').status_code,401)
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
        self.assertEqual(self.client.post('/api/owner/wallet/timeout',json={'visit_timeout_minutes':30}).status_code,403)
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':True}
        self.assertEqual(self.client.get('/api/owner/wallet').status_code,428)

    def test_timeout_is_strict_and_does_not_change_roles(self):
        self.cfg['local_post']=1
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        with patch.object(api,'persist_configuration') as save,patch.object(api,'rpc',return_value={'ok':True}):
            for value in (True,0,1441,'30'):
                self.assertEqual(self.client.post('/api/owner/wallet/timeout',json={'visit_timeout_minutes':value}).status_code,422)
            response=self.client.post('/api/owner/wallet/timeout',json={'visit_timeout_minutes':45})
            self.assertEqual(response.status_code,200)
            self.assertEqual(save.call_args.args[0]['primary_post'],1)
            self.assertEqual(save.call_args.args[0]['visit_timeout_minutes'],45)

    def test_promotion_requires_both_confirmations(self):
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        with patch.object(api,'store_context') as store:
            for fence,single in [(False,True),(True,False)]:
                r=self.client.post('/api/owner/wallet/promote',json={'confirmation':'PROMOTE POST 7','old_primary_fenced':fence,'single_node_confirmed':single})
                self.assertEqual(r.status_code,409)
            store.assert_not_called()

    def test_peer_urls_reject_credentials_public_dns_and_paths(self):
        for url in ('http://example.com','https://10.0.0.1','http://user:pass@10.0.0.1','http://8.8.8.8','http://10.0.0.1/api','http://10.0.0.1:99999'):
            with self.assertRaises(ValueError):api.validate_peer_url(url)
        self.assertEqual(api.validate_peer_url('http://10.0.0.1:80/'),'http://10.0.0.1:80')

    def test_new_post_enrollment_is_bound_to_connecting_address(self):
        self.cfg['local_post']=1
        @contextmanager
        def fake(cfg):yield MagicMock()
        body={'site_id':'SITE','sender_post':3,'timestamp':int(time.time()),'payload':{'url':'http://10.0.0.3'}}
        path='/api/wallet/internal/enroll';headers={'X-Wallet-Signature':api.signature('test-site-secret',path,body),'X-Real-IP':'10.0.0.4'}
        with patch.object(api,'store_context',fake),patch.object(api,'rpc',return_value={'ok':True}),patch.object(api,'persist_configuration') as save:
            self.assertEqual(self.client.post(path,json=body,headers=headers).status_code,409);save.assert_not_called()
            headers['X-Real-IP']='10.0.0.3'
            self.assertEqual(self.client.post(path,json=body,headers=headers).status_code,200)
            self.assertEqual(save.call_args.args[0]['peer_urls']['3'],'http://10.0.0.3')

    def test_automatic_report_claim_is_authenticated_and_not_repeated(self):
        import os
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.cfg['local_post']=1;store=MagicMock();store._operation.side_effect=[None,{'status':'committed'}]
        @contextmanager
        def fake(cfg):yield store
        day=datetime.now(ZoneInfo('Asia/Tashkent')).date().isoformat()
        with patch.dict(os.environ,{'TELEGRAM_SETUP_KEY':'fixture-report-key'}),patch.object(api,'store_context',fake),patch.object(api,'coordinator'):
            self.assertEqual(self.client.post('/api/wallet/report-claim',json={'day':day}).status_code,401)
            headers={'Authorization':'Bearer fixture-report-key'}
            self.assertTrue(self.client.post('/api/wallet/report-claim',json={'day':day},headers=headers).json()['allowed'])
            self.assertFalse(self.client.post('/api/wallet/report-claim',json={'day':day},headers=headers).json()['allowed'])

    def test_admin_cannot_restore_customer_money(self):
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
        self.assertEqual(self.client.post('/api/owner/wallet/recovery/1',json={'uid':'7C212602'}).status_code,403)

    def test_owner_diagnostics_is_read_only_and_releases_locks_before_rpc(self):
        self.assertEqual(self.client.get('/api/owner/wallet/diagnostics').status_code,401)
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
        self.assertEqual(self.client.get('/api/owner/wallet/diagnostics').status_code,403)
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        active=[False]
        proof={'proof_version':2,'journal_digest':'a'*64,'state_digest':'b'*64,'operation_count':3,'pending_count':0}
        @contextmanager
        def fake(cfg):
            active[0]=True
            store=MagicMock();store.diagnostics.return_value=proof
            try:yield store
            finally:active[0]=False
        def remote(cfg,post,action,payload):
            self.assertFalse(active[0]);self.assertFalse(api.control_lock._is_owned())
            self.assertEqual(action,'diagnostics')
            return {**proof,'local_post':post,'primary_post':1,'standby_post':7,'generation':2}
        with patch.object(api,'store_context',fake),patch.object(api,'rpc',side_effect=remote),patch.object(api,'persist_configuration') as save:
            response=self.client.get('/api/owner/wallet/diagnostics')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['state'],'in-sync');save.assert_not_called()

    def test_old_ready_ack_never_enables_new_redundancy_mode(self):
        self.cfg['local_post']=1;self.cfg['single_node']=True
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        @contextmanager
        def fake(cfg):
            store=MagicMock();store.pending_operations.return_value=[]
            store.digest.return_value='a'*64;store.state_digest.return_value='b'*64
            yield store
        def remote(cfg,post,action,payload):
            return {'operation_ids':[]} if action=='replica-pending' else {'ok':True}
        with patch.object(api,'store_context',fake),patch.object(api,'rpc',side_effect=remote),patch.object(api,'coordinator') as coordinator,patch.object(api,'persist_configuration') as save:
            coordinator.return_value.catch_up.return_value=0
            response=self.client.post('/api/owner/wallet/synchronize')
        self.assertEqual(response.status_code,503);self.assertTrue(self.cfg['single_node']);self.assertFalse(self.cfg['standby_ready'])
        self.assertEqual(save.call_args.args[2],'wallet_proof_failed')
    def test_customer_registry_and_local_import_require_owner_and_reject_balance_edits(self):
        paths=['/api/owner/wallet/customers','/api/owner/wallet/local-import']
        for path in paths:self.assertEqual(self.client.get(path).status_code,401)
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
        for path in paths:self.assertEqual(self.client.get(path).status_code,403)
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        payload={'uid':'ABCD','enabled':True,'status':'active','expected_revision':0,'balance_sum':1000}
        self.assertEqual(self.client.post(paths[0],json=payload).status_code,422)
        payload={'uid':'ABCD','amount_sum':True,'confirmation':'IMPORT ABCD 1'}
        self.assertEqual(self.client.post(paths[1],json=payload).status_code,422)
    def test_local_import_releases_controller_locks_before_rpc(self):
        from app import local_balance_import
        from app.wash_logic import wash_runtime
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        calls=[]
        def transfer(*args,**kwargs):
            calls.append(kwargs.get('prepare_only',False))
            held=bool(kwargs.get('prepare_only'))
            self.assertEqual(api.control_lock._is_owned(),held)
            self.assertEqual(wash_runtime.lock._is_owned(),held)
            return {'ok':True,'prepared':held}
        with patch.object(wash_runtime,'shared_wallet_enabled',True),patch.object(wash_runtime,'state',{'creditSum':0}),patch.object(local_balance_import,'transfer',side_effect=transfer):
            response=self.client.post('/api/owner/wallet/local-import',json={'uid':'ABCD','amount_sum':35000,'confirmation':'IMPORT ABCD 35000'})
        self.assertEqual(response.status_code,200);self.assertEqual(calls,[True,False])
    def test_stale_customer_edit_never_changes_registry(self):
        from app import customer_registry
        self.cfg['local_post']=1
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        @contextmanager
        def fake(cfg):
            store=MagicMock();store.inspect.return_value={'state':{'revision':4}};yield store
        with patch.object(customer_registry,'configuration',return_value=self.cfg),patch.object(customer_registry,'store_context',fake),patch.object(customer_registry,'owner_operation') as operation:
            response=self.client.post('/api/owner/wallet/customers',json={'uid':'ABCD','expected_revision':3,'status':'lost'})
        self.assertEqual(response.status_code,409);operation.assert_not_called()
    def test_setup_with_local_money_requires_explicit_migration_confirmation(self):
        from app import local_balance_import
        from app.wash_logic import wash_runtime
        self.cfg['enabled']=False
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
        @contextmanager
        def database():
            conn=MagicMock()
            def execute(sql,*args):
                result=MagicMock();result.fetchone.return_value={'amount':35000} if 'sum(balance_sum)' in sql else {'count':0};return result
            conn.execute.side_effect=execute;yield conn
        @contextmanager
        def store(cfg):yield MagicMock()
        payload={'primary_post':1,'standby_post':7,'peer_urls':{'1':'http://10.0.0.1','7':'http://10.0.0.7'}}
        with patch.object(api,'db',database),patch.object(api,'store_context',store),patch.object(api,'persist_configuration'),patch.object(local_balance_import,'stage_all') as stage,patch.object(wash_runtime,'shared_wallet_enabled',False),patch.object(wash_runtime,'snapshot',return_value={'state':{'creditSum':0}}):
            self.assertEqual(self.client.post('/api/admin/wallet/setup',json=payload).status_code,409)
            self.assertEqual(self.client.post('/api/admin/wallet/setup',json={**payload,'migrate_local_balances':True,'migration_confirmation':'wrong'}).status_code,409)
            stage.assert_not_called()
            response=self.client.post('/api/admin/wallet/setup',json={**payload,'migrate_local_balances':True,'migration_confirmation':'MIGRATE LOCAL BALANCES POST 7'})
            self.assertEqual(response.status_code,200);stage.assert_called_once()


class RpcConflictTests(unittest.TestCase):
    def test_signed_business_rejection_keeps_definitive_flag(self):
        from app.wallet_domain import WalletConflict
        cfg={'site_id':'SITE','local_post':2,'peer_urls':{'1':'http://10.0.0.1'}}
        def respond(url,*,json,headers):
            data={'detail':'VIP-карта уже используется на другом посту','operation_status':'not-recorded',
                  'request_digest':hashlib.sha256(api.canonical(json)).hexdigest()}
            response=MagicMock(status_code=409)
            response.json.return_value=data
            response.headers={'X-Wallet-Signature':api.signature('test-secret','/api/wallet/internal/execute',data)}
            return response
        with patch.object(api,'identity',return_value={'site_token':'test-secret'}),patch.object(api.httpx,'Client') as client:
            client.return_value.__enter__.return_value.post.side_effect=respond
            with self.assertRaises(WalletConflict) as raised:
                api.rpc(cfg,1,'execute',{})
            self.assertEqual(str(raised.exception),'VIP-карта уже используется на другом посту')
            self.assertTrue(raised.exception.definitive)
