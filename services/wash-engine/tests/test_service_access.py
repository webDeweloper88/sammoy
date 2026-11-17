import os
import unittest
from unittest.mock import patch, Mock
from app import service_access as access
from app.wash_logic import WashRuntime


class ServicePolicyTests(unittest.TestCase):
    def tearDown(self):
        access._pending = access._enrollment = None
        access._grants.clear()

    def test_pin_length_limits_for_enrollment_and_login(self):
        from pydantic import ValidationError
        for model, extra in [(access.Enroll,dict(name='Test',password='owner-password')),(access.Pin,dict(challenge='test-challenge'))]:
            for pin in ['1234','0000','123456789012']:
                self.assertEqual(model(pin=pin,**extra).pin,pin)
            for pin in ['123','1234567890123','12ab','１２３４']:
                with self.assertRaises(ValidationError):
                    model(pin=pin,**extra)

    def test_idle_requires_no_money_session_or_output(self):
        runtime = WashRuntime()
        self.assertTrue(access.idle(runtime))
        for key, value in [('creditSum',1),('activeMode','water'),('requestedOutput','water'),('walletTransferPending',True)]:
            runtime.state[key]=value
            self.assertFalse(access.idle(runtime),key)
            runtime.state[key]=0 if key=='creditSum' else None
        runtime.active_session_id=12
        self.assertFalse(access.idle(runtime))

    def test_service_and_revoked_cards_never_reach_wallet(self):
        for active in (True,False):
            runtime=WashRuntime();runtime.shared_wallet_enabled=True
            conn=Mock();conn.execute.return_value.fetchone.return_value={'id':9,'active':active}
            with patch.object(access,'db') as database, patch('app.wallet_post.freeze') as freeze:
                database.return_value.__enter__.return_value=conn
                runtime._apply_rfid_card_locked('TEST-SERVICE',{'sak':8,'atqa':'0400'})
            freeze.assert_not_called()
            self.assertEqual(runtime.state['creditSum'],0)
            self.assertEqual(conn.execute.call_count,1)

    def test_customer_card_continues_to_wallet(self):
        runtime=WashRuntime();runtime.shared_wallet_enabled=True
        conn=Mock();conn.execute.return_value.fetchone.return_value=None
        with patch.object(access,'db') as database, patch('app.wallet_post.freeze',side_effect=RuntimeError('reached wallet')) as freeze, patch('app.wallet_post.pending_job',return_value=None):
            database.return_value.__enter__.return_value=conn
            runtime._apply_rfid_card_locked('TEST-CUSTOMER',{'sak':8,'atqa':'0400'})
        freeze.assert_called_once_with(runtime)

    def test_confirmation_is_bound_to_body_method_session_and_one_use(self):
        import hashlib,time
        user={'_jti':'test'}
        def grant():access._grants['key']=dict(until=time.monotonic()+20,jti='test',method='POST',path='/api/owner/wallet/promote',digest=hashlib.sha256(b'{}').hexdigest())
        grant();self.assertFalse(access.consume_grant('key',user,'POST','/api/owner/wallet/promote',b'{"other":true}'))
        grant();self.assertFalse(access.consume_grant('key',{'_jti':'different'},'POST','/api/owner/wallet/promote',b'{}'))
        grant();self.assertTrue(access.consume_grant('key',user,'POST','/api/owner/wallet/promote',b'{}'))
        self.assertFalse(access.consume_grant('key',user,'POST','/api/owner/wallet/promote',b'{}'))

    def test_critical_routes(self):
        for path in ['/api/owner/wallet/promote','/api/wallet-management/change','/api/owner/rfid/cards','/api/owner/updates/start','/api/system/actions','/api/auth/account']:
            self.assertTrue(access.critical(path,'POST'))
            self.assertFalse(access.critical(path,'GET'))
        self.assertFalse(access.critical('/api/owner/wash/parameters','POST'))


@unittest.skipUnless(os.getenv('SERVICE_ACCESS_TEST_DATABASE'),'isolated PostgreSQL required')
class ServiceDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.main import app, SCHEMA_SQL, wash_runtime
        from app.db import open_pool, db
        from app.security import hash_password
        from fastapi.testclient import TestClient
        open_pool();cls.db=staticmethod(db);cls.runtime=wash_runtime;cls.client=TestClient(app)
        with db() as conn:
            from app.wallet_store import WALLET_SCHEMA_SQL
            from app.wallet_post import POST_SCHEMA_SQL
            conn.execute(SCHEMA_SQL);conn.execute(access.SCHEMA_SQL);conn.execute(WALLET_SCHEMA_SQL);conn.execute(POST_SCHEMA_SQL)
            cls.owner=conn.execute("INSERT INTO auth_users(login,role,display_name,password_hash) VALUES('service-test-owner','owner','Test',%s) ON CONFLICT(login) DO UPDATE SET password_hash=EXCLUDED.password_hash RETURNING *",(hash_password('test-owner-password'),)).fetchone()
            conn.commit()
        from app.security import create_access_token
        cls.password_token=create_access_token(cls.owner)[0]

    def setUp(self):
        access._pending=access._enrollment=None
        self.runtime.state.update(creditSum=0,activeMode=None,requestedOutput=None,walletTransferPending=False)
        self.runtime.active_session_id=None;self.runtime.shared_wallet_enabled=False
        with self.db() as conn:
            conn.execute('DELETE FROM owner_service_sessions');conn.execute('DELETE FROM owner_service_cards');conn.execute('DELETE FROM auth_login_attempts')
            conn.execute("DELETE FROM wash_sessions WHERE card_uid LIKE 'TEST-%%'")
            conn.execute("DELETE FROM rfid_cards WHERE uid LIKE 'TEST-%%'")
            conn.commit()

    def request(self,method,path,body=None,token=None,headers=None):
        return self.client.request(method,path,json=body,headers={'Authorization':'Bearer '+(token or self.password_token),**(headers or {})})

    def enroll(self):
        response=self.request('POST','/api/owner/service-cards/enroll',{'name':'Test service','pin':'1234','password':'test-owner-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(access.intercept(self.runtime,'TEST-SERVICE-UID'))
        response=self.request('POST','/api/owner/service-cards/finish')
        self.assertEqual(response.status_code,200,response.text)
        access.intercept(self.runtime,'TEST-SERVICE-UID')
        return self.client.get('/api/auth/service-challenge').json()['challenge']

    def login(self,challenge,pin='1234'):
        return self.client.post('/api/auth/service-pin',json={'challenge':challenge,'pin':pin})

    def test_enroll_login_replay_and_revoke(self):
        challenge=self.enroll();response=self.login(challenge)
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertEqual(result['user']['auth_method'],'nfc_pin')
        token=result['access_token'];card=result['user']['service_card_id']
        self.assertEqual(self.login(challenge).status_code,409)
        self.assertEqual(self.request('GET','/api/auth/me',token=token).status_code,200)
        response=self.request('DELETE',f'/api/owner/service-cards/{card}',{'password':'test-owner-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.request('GET','/api/auth/me',token=token).status_code,401)
        self.assertTrue(access.intercept(self.runtime,'TEST-SERVICE-UID'))
        with self.db() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM rfid_cards WHERE uid='TEST-SERVICE-UID'").fetchone())
            self.assertNotEqual(conn.execute('SELECT pin_hash FROM owner_service_cards').fetchone()['pin_hash'],'123456')

    def test_pin_lockout_survives_new_challenge(self):
        challenge=self.enroll()
        for _ in range(5):self.assertEqual(self.login(challenge,'000000').status_code,403)
        self.assertEqual(self.login(challenge).status_code,429)
        access._pending=None;access.intercept(self.runtime,'TEST-SERVICE-UID')
        self.assertEqual(self.login(access._pending['nonce']).status_code,429)

    def test_idle_checked_again_at_pin_submission(self):
        challenge=self.enroll();self.runtime.state['creditSum']=1000
        self.assertEqual(self.login(challenge).status_code,409)
        self.assertEqual(self.runtime.state['creditSum'],1000)

    def test_card_session_needs_specific_password_confirmation(self):
        token=self.login(self.enroll()).json()['access_token']
        self.assertEqual(self.request('POST','/api/owner/wallet/promote',{},token).status_code,428)
        import json
        body=json.dumps({'current_password':'test-owner-password','display_name':'Updated'})
        response=self.request('POST','/api/auth/confirm-action',{'password':'test-owner-password','method':'POST','path':'/api/auth/account','body':body},token)
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/api/auth/account',content=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'X-Owner-Confirmation':response.json()['grant']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['auth_method'],'nfc_pin')
        self.assertEqual(self.request('GET','/api/auth/me',token=response.json()['access_token']).status_code,200)

    def test_customer_card_with_money_cannot_be_registered(self):
        with self.db() as conn:
            conn.execute("INSERT INTO rfid_cards(uid,card_type,status,enabled,balance_sum) VALUES('TEST-CUSTOMER','customer','active',TRUE,5000) ON CONFLICT(uid) DO NOTHING");conn.commit()
        self.request('POST','/api/owner/service-cards/enroll',{'name':'Test','pin':'123456','password':'test-owner-password'})
        self.assertTrue(access.intercept(self.runtime,'TEST-CUSTOMER'))
        self.assertEqual(self.request('POST','/api/owner/service-cards/finish').status_code,409)
        with self.db() as conn:
            self.assertEqual(conn.execute("SELECT balance_sum FROM rfid_cards WHERE uid='TEST-CUSTOMER'").fetchone()['balance_sum'],5000)

    def test_server_expires_inactive_card_session(self):
        token=self.login(self.enroll()).json()['access_token']
        with self.db() as conn:
            conn.execute("UPDATE owner_service_sessions SET last_seen_at=now()-interval '3 minutes'");conn.commit()
        self.assertEqual(self.request('GET','/api/auth/me',token=token).status_code,401)

    def test_enrollment_cannot_be_finished_by_another_session(self):
        self.request('POST','/api/owner/service-cards/enroll',{'name':'Test','pin':'123456','password':'test-owner-password'})
        access.intercept(self.runtime,'TEST-NEW-SERVICE')
        from app.security import create_access_token
        other_token=create_access_token(self.owner)[0]
        self.assertEqual(self.request('POST','/api/owner/service-cards/finish',token=other_token).status_code,409)

    def test_owner_password_confirmation_is_rate_limited(self):
        token=self.login(self.enroll()).json()['access_token']
        body={'password':'incorrect-password','method':'POST','path':'/api/owner/wallet/promote','body':'{}'}
        for _ in range(5):
            self.assertEqual(self.request('POST','/api/auth/confirm-action',body,token).status_code,403)
        body['password']='test-owner-password'
        self.assertEqual(self.request('POST','/api/auth/confirm-action',body,token).status_code,429)

    def begin_existing(self, uid, balance=0, card_type='customer'):
        with self.db() as conn:
            conn.execute("INSERT INTO rfid_cards(uid,card_type,balance_sum) VALUES(%s,%s,%s) ON CONFLICT(uid) DO UPDATE SET card_type=EXCLUDED.card_type,balance_sum=EXCLUDED.balance_sum", (uid,card_type,balance));conn.commit()
        response=self.request('POST','/api/owner/service-cards/enroll',{'name':'Converted','pin':'123456','password':'test-owner-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(access.intercept(self.runtime,uid))

    def test_zero_customer_conversion_preserves_history(self):
        uid='TEST-ZERO-CUSTOMER'
        self.begin_existing(uid)
        with self.db() as conn:
            session=conn.execute("INSERT INTO wash_sessions(card_uid,status,paid_sum,total_spent_sum) VALUES(%s,'closed',500,500) RETURNING id", (uid,)).fetchone()['id'];conn.commit()
        response=self.request('POST','/api/owner/service-cards/finish')
        self.assertEqual(response.status_code,200,response.text)
        with self.db() as conn:
            row=conn.execute('SELECT * FROM rfid_cards WHERE uid=%s',(uid,)).fetchone()
            self.assertEqual(row['balance_sum'],0)
            self.assertEqual(row['card_type'],'service')
            self.assertFalse(row['enabled'])
            self.assertEqual(conn.execute('SELECT card_uid,total_spent_sum FROM wash_sessions WHERE id=%s',(session,)).fetchone(),dict(card_uid=uid,total_spent_sum=500))
        access.intercept(self.runtime,uid)
        self.assertEqual(self.runtime.state['lastRfidStatus'],'service_pin_required')

    def test_vip_with_zero_balance_is_rejected(self):
        self.begin_existing('TEST-ZERO-VIP',card_type='vip')
        self.assertEqual(access._enrollment['error'],'service_card_not_customer')
        self.assertEqual(self.request('POST','/api/owner/service-cards/finish').status_code,409)

    def test_balance_added_after_capture_blocks_commit(self):
        uid='TEST-CHANGING-CUSTOMER';self.begin_existing(uid)
        with self.db() as conn:
            conn.execute('UPDATE rfid_cards SET balance_sum=500 WHERE uid=%s',(uid,));conn.commit()
        response=self.request('POST','/api/owner/service-cards/finish')
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['detail'],'service_card_has_balance')
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT balance_sum FROM rfid_cards WHERE uid=%s',(uid,)).fetchone()['balance_sum'],500)
            self.assertIsNone(conn.execute('SELECT 1 FROM owner_service_cards WHERE uid=%s',(uid,)).fetchone())

    def test_running_session_rejects_zero_customer(self):
        uid='TEST-RUNNING-CUSTOMER';self.begin_existing(uid)
        with self.db() as conn:
            conn.execute("INSERT INTO wash_sessions(card_uid,status) VALUES(%s,'running')",(uid,));conn.commit()
        self.assertEqual(self.request('POST','/api/owner/service-cards/finish').json()['detail'],'service_card_pending')

    def test_unclaimed_money_rejects_zero_customer(self):
        uid='TEST-RECOVERY-CUSTOMER';self.begin_existing(uid)
        with self.db() as conn:
            session=conn.execute("INSERT INTO wash_sessions(card_uid,status) VALUES(%s,'closed') RETURNING id",(uid,)).fetchone()['id']
            conn.execute("INSERT INTO recovery_credits(wash_session_id,amount_sum,reason) VALUES(%s,500,'test')",(session,));conn.commit()
        self.assertEqual(self.request('POST','/api/owner/service-cards/finish').json()['detail'],'service_card_pending')

    def test_additive_schema_migration_preserves_existing_money_and_history(self):
        from app.main import SCHEMA_SQL
        with self.db() as conn:
            try:
                conn.execute('CREATE SCHEMA service_migration_fixture')
                conn.execute('SET LOCAL search_path TO service_migration_fixture')
                conn.execute(SCHEMA_SQL)
                self.assertIsNone(conn.execute("SELECT to_regclass('owner_service_cards') AS name").fetchone()['name'])
                conn.execute("INSERT INTO rfid_cards(uid,card_type,balance_sum) VALUES('MIGRATION-CARD','customer',25000)")
                conn.execute("INSERT INTO wash_sessions(card_uid,status,paid_sum,total_spent_sum) VALUES('MIGRATION-CARD','closed',30000,5000)")
                before=conn.execute("SELECT balance_sum,(SELECT sum(paid_sum) FROM wash_sessions) AS paid,(SELECT sum(total_spent_sum) FROM wash_sessions) AS spent FROM rfid_cards WHERE uid='MIGRATION-CARD'").fetchone()
                conn.execute(access.SCHEMA_SQL)
                conn.execute(access.SCHEMA_SQL)
                after=conn.execute("SELECT balance_sum,(SELECT sum(paid_sum) FROM wash_sessions) AS paid,(SELECT sum(total_spent_sum) FROM wash_sessions) AS spent FROM rfid_cards WHERE uid='MIGRATION-CARD'").fetchone()
                self.assertEqual(before,after)
                self.assertIsNotNone(conn.execute("SELECT to_regclass('owner_service_cards') AS name").fetchone()['name'])
            finally:
                conn.rollback()
