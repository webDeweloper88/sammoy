"""Financial integration tests: only the disposable labrix_engine_test database."""
import os
import unittest
from uuid import uuid4
from unittest.mock import patch,AsyncMock,Mock
import httpx
import test_wash_logic
from app import main
from app.db import db,open_pool,close_pool
from app.wash_logic import WashRuntime
from app.wallet_payments import bind_new_intent

@unittest.skipUnless(os.environ.get('LABRIX_CLICK_TEST_DB')=='isolated','Disposable database required')
class ClickLedgerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        open_pool()
        with db() as c:
            assert c.info.dbname=='labrix_engine_test'
            c.execute(main.SCHEMA_SQL)
            from app.wallet_store import WALLET_SCHEMA_SQL
            from app.wallet_post import POST_SCHEMA_SQL
            from app.wallet_payments import PAYMENT_SCHEMA_SQL
            c.execute(WALLET_SCHEMA_SQL);c.execute(POST_SCHEMA_SQL);c.execute(PAYMENT_SCHEMA_SQL);c.commit()
    @classmethod
    def tearDownClass(cls):close_pool()
    def setUp(self):
        with db() as c:c.execute('TRUNCATE wash_sessions,click_payment_intents,license_cache CASCADE');c.commit()
        self.runtime=WashRuntime();self.runtime.shared_wallet_enabled=False;self.runtime._flush_usage_locked=Mock()
        self.runtime.params['topUpBonus']={'enabled':False,'percent':10}
        p=patch.object(main,'wash_runtime',self.runtime);p.start();self.addCleanup(p.stop)
        self.provider=uuid4()
    def invoice(self,*,origin=True):
        session,_=bind_new_intent(self.runtime) if origin else (None,None)
        with db() as c:
            row=c.execute("INSERT INTO click_payment_intents(id,gateway_intent_id,amount_sum,status,gateway_status,bonus_sum,wallet_origin_session_id) VALUES(%s,%s,1000,'paid','paid',0,%s) RETURNING *",(uuid4(),self.provider,session)).fetchone();c.commit();return row
    def totals(self):
        with db() as c:
            return c.execute('SELECT count(*) AS n,COALESCE(sum(amount_sum),0) AS amount FROM payments').fetchone()
    async def test_repeated_provider_payment_is_credited_exactly_once(self):
        row=self.invoice();main.apply_click_credit_once(row['id']);main.apply_click_credit_once(row['id'])
        self.assertEqual(self.runtime.state['creditSum'],1000);self.assertEqual(self.totals(),{'n':1,'amount':1000})
    async def test_retry_after_ledger_commit_without_intent_marker_is_idempotent(self):
        row=self.invoice();main.apply_click_credit_once(row['id'])
        with db() as c:c.execute("UPDATE click_payment_intents SET status='paid',credited_at=NULL WHERE id=%s",(row['id'],));c.commit()
        main.apply_click_credit_once(row['id']);self.assertEqual(self.runtime.state['creditSum'],1000);self.assertEqual(self.totals()['n'],1)
    async def test_late_payment_never_credits_another_customer(self):
        row=self.invoice();self.runtime.active_session_id=None;self.runtime.state['activeSessionId']=None
        result=main.apply_click_credit_once(row['id']);main.apply_click_credit_once(row['id'])
        self.assertEqual(result['wallet_credit_destination'],'recovery');self.assertEqual(self.runtime.state['creditSum'],0)
        with db() as c:self.assertEqual(c.execute('SELECT count(*) n,sum(amount_sum) amount FROM recovery_credits').fetchone(),{'n':1,'amount':1000})
    async def test_license_block_preserves_confirmed_payment_in_recovery(self):
        row=self.invoice();self.runtime.state['licenseLocked']=True
        result=main.apply_click_credit_once(row['id']);self.assertEqual(result['wallet_credit_destination'],'recovery');self.assertEqual(self.totals()['amount'],1000)
    async def test_old_unknown_origin_is_preserved_not_given_to_current_customer(self):
        row=self.invoice(origin=False);result=main.apply_click_credit_once(row['id'])
        self.assertEqual(result['wallet_credit_destination'],'recovery');self.assertEqual(self.runtime.state['creditSum'],0)
    async def test_ack_failure_then_recovery_does_not_duplicate_credit(self):
        row=self.invoice();config={'enabled':True,'gateway_url':'https://gateway.test','site_code':'test','post_no':1,'site_token':'test-only'}
        payment={'id':str(self.provider),'amount_sum':1000,'status':'paid','merchant_trans_id':'test'}
        client=AsyncMock();client.__aenter__.return_value=client
        client.get.return_value=Mock(status_code=200,json=Mock(return_value={'payments':[payment]}))
        client.post.side_effect=[httpx.ConnectError('ACK lost'),Mock(status_code=200,json=Mock(return_value={'acknowledged':1}))]
        with patch.object(main.httpx,'AsyncClient',return_value=client),patch.object(main,'read_license_cache',return_value=None):
            with self.assertRaises(httpx.ConnectError):await main.sync_click_payments(config)
            result=await main.sync_click_payments(config)
        self.assertEqual(result['acknowledged'],1);self.assertEqual(self.runtime.state['creditSum'],1000);self.assertEqual(self.totals()['n'],1)

    async def test_signed_offline_file_import_works_without_gateway(self):
        import io,json
        from starlette.datastructures import UploadFile
        from test_signed_license import SignedLicenseTests
        helper=SignedLicenseTests();helper.setUp()
        self.runtime.state['outputsOffConfirmed']=True
        try:
            with patch.object(main,'get_license_settings',return_value=helper.config):
                file=UploadFile(filename='licence.json',file=io.BytesIO(json.dumps({'schema':'labrix.license-file.v1','authorization':helper.envelope}).encode()))
                result=await main.import_license_authorization(file,{'role':'admin'})
            self.assertFalse(result['license']['locked']);self.assertEqual(result['license']['authorization_mode'],'local_signed')
            with db() as c:self.assertEqual(c.execute('SELECT raw_payload FROM license_cache WHERE id=1').fetchone()['raw_payload']['authorization'],helper.envelope)
        finally:helper.doCleanups()

    async def test_wrong_controller_file_does_not_replace_cached_license(self):
        import io,json
        from fastapi import HTTPException
        from starlette.datastructures import UploadFile
        from test_signed_license import SignedLicenseTests
        helper=SignedLicenseTests();helper.setUp();self.runtime.state['outputsOffConfirmed']=True
        try:
            with patch.object(main,'get_license_settings',return_value=helper.config),patch.object(main,'hardware_sync_payload',return_value={'hardware_fingerprint_hash':'f'*64}):
                file=UploadFile(filename='licence.json',file=io.BytesIO(json.dumps({'schema':'labrix.license-file.v1','authorization':helper.envelope}).encode()))
                with self.assertRaises(HTTPException) as error:await main.import_license_authorization(file,{'role':'admin'})
                self.assertEqual(error.exception.status_code,400)
            with db() as c:self.assertEqual(c.execute('SELECT count(*) n FROM license_cache').fetchone()['n'],0)
        finally:helper.doCleanups()

    async def test_online_signed_sync_persists_verified_response_without_a_lease(self):
        from test_signed_license import SignedLicenseTests
        helper=SignedLicenseTests();helper.setUp()
        client=AsyncMock();client.__aenter__.return_value=client;client.post.return_value=Mock(status_code=200)
        def answer(url,params,headers):
            body={**helper.envelope,'nonce':params['nonce']};body.pop('signature')
            import base64
            from app.license_authorization import canonical
            body['signature']=base64.urlsafe_b64encode(helper.private.sign(canonical(body))).decode()
            return Mock(status_code=200,json=Mock(return_value={'license':{'authorization':body}}))
        client.get.side_effect=answer
        try:
            with patch.object(main,'get_license_settings',return_value=helper.config),patch.object(main,'sync_pending_offline_license_codes',AsyncMock()),patch.object(main.httpx,'AsyncClient',return_value=client):
                result=await main.sync_license_once()
            self.assertTrue(result['synced']);self.assertFalse(result['license']['locked']);self.assertIsNone(result['license']['online_lease_until'])
        finally:helper.doCleanups()
