import base64
import copy
import unittest
from datetime import UTC,datetime,timedelta
from unittest.mock import Mock,patch,AsyncMock
import httpx
import test_wash_logic
from app import main,license_authorization as auth
from app.wash_logic import WashRuntime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

class SignedLicenseTests(unittest.TestCase):
    def setUp(self):
        self.private=Ed25519PrivateKey.generate();public=base64.urlsafe_b64encode(self.private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
        self.config={'enabled':True,'site_code':'site','post_no':1,'site_token':'test-only','gateway_url':'https://gateway.test','sync_interval_seconds':900,'grace_seconds':604800}
        self.hw={'hardware_fingerprint_hash':'a'*64}
        self.license={'site_code':'site','post_no':1,'enabled':True,'locked':False,'reason':'valid','license_duration_type':'permanent','operation_mode':'online','authorization_mode':'local_signed','online_lease_until':None,'valid_until':None,'lifecycle':{'state':'active','revision':1,'controller_generation':1}}
        self.issued=datetime.now(UTC)-timedelta(days=60)
        self.envelope=self.sign()
        for p in (patch.object(auth,'public_key',return_value=public),patch.object(auth,'clock',auth.LicenseClock()),patch.object(main,'hardware_sync_payload',return_value=self.hw)):
            p.start();self.addCleanup(p.stop)
    def sign(self,license=None,issued=None):
        body={'schema':auth.DOMAIN,'site_code':'site','post_no':1,'hardware_fingerprint_hash':'a'*64,'nonce':'1'*32,'issued_at':(issued or self.issued).isoformat(),'license':copy.deepcopy(license or self.license)}
        return {**body,'signature':base64.urlsafe_b64encode(self.private.sign(auth.canonical(body))).decode().rstrip('=')}
    def row(self,envelope=None,**changes):
        return {'enabled':True,'locked':False,'state':'valid','reason':'valid','site_code':'site','post_no':1,'machine_id':None,'days_left':None,'valid_until':None,'last_success_at':self.issued,'last_attempt_at':self.issued,'next_sync_at':self.issued,'grace_until':self.issued+timedelta(days=7),'last_error':'network unavailable','raw_payload':{'authorization':envelope or self.envelope},**changes}
    def evaluate(self,row=None):return main.evaluate_license_lock(row or self.row(),self.config)
    def test_permanent_signed_license_survives_sixty_days_without_server(self):
        result=self.evaluate();self.assertFalse(result['locked']);self.assertEqual(result['authorization_mode'],'local_signed');self.assertEqual(result['state'],'grace')
    def test_unsigned_cache_fields_cannot_change_signed_decision(self):
        self.assertFalse(self.evaluate(self.row(enabled=False,valid_until=datetime.now(UTC)-timedelta(days=1)))['locked'])
        disabled={**self.license,'enabled':False,'locked':True}
        self.assertTrue(self.evaluate(self.row(self.sign(disabled),enabled=True,locked=False))['locked'])
    def test_signature_tampering_or_other_controller_is_rejected(self):
        broken=copy.deepcopy(self.envelope);broken['license']['enabled']=False
        self.assertTrue(self.evaluate(self.row(broken))['locked'])
        with patch.object(main,'hardware_sync_payload',return_value={'hardware_fingerprint_hash':'b'*64}):self.assertTrue(self.evaluate()['locked'])
        self.config['site_code']='other';self.assertTrue(self.evaluate()['locked'])
    def test_finite_license_expires_at_signed_date_not_network_deadline(self):
        future={**self.license,'license_duration_type':'time_limited','valid_until':(datetime.now(UTC)+timedelta(days=1)).isoformat()}
        self.assertFalse(self.evaluate(self.row(self.sign(future)))['locked'])
        expired={**future,'valid_until':(datetime.now(UTC)-timedelta(seconds=1)).isoformat()}
        self.assertTrue(self.evaluate(self.row(self.sign(expired)))['locked'])
    def test_revocation_is_preserved_after_server_disappears(self):
        denied={**self.license,'enabled':False,'locked':True,'lifecycle':{'state':'revoked','revision':2,'controller_generation':1}}
        self.assertTrue(self.evaluate(self.row(self.sign(denied)))['locked'])
    def test_nonce_and_signed_history_prevent_replaying_an_older_permission(self):
        with self.assertRaises(ValueError):auth.verify(self.envelope,self.config,self.hw,nonce='2'*32)
        newer=self.sign(issued=datetime.now(UTC))
        with self.assertRaises(ValueError):auth.verify(self.envelope,self.config,self.hw,previous=newer)
        changed={**self.license,'lifecycle':{'revision':0,'controller_generation':0}}
        with self.assertRaises(ValueError):auth.verify(self.sign(changed,datetime.now(UTC)),self.config,self.hw,previous=self.envelope)
    def test_expired_legacy_cache_is_not_silently_promoted_to_permanent(self):
        self.assertTrue(self.evaluate(self.row(raw_payload={'operation_mode':'online','license_duration_type':'permanent'}))['locked'])
    def test_local_clock_does_not_go_backwards_and_persisted_floor_survives_boot(self):
        now=datetime.now(UTC);clock=auth.LicenseClock()
        with patch.object(auth.time,'monotonic',side_effect=[1,11]):
            self.assertEqual(clock.now(wall=now),now)
            self.assertEqual(clock.now(wall=now-timedelta(days=1)),now+timedelta(seconds=10))
        fresh=auth.LicenseClock();self.assertGreaterEqual(fresh.now(wall=now-timedelta(days=1),persisted=now),now)
    def test_existing_signed_cash_only_commissioning_file_works_offline(self):
        import json
        grant={'site':'site','post':1,'hardware_fingerprint_hash':'a'*64,'action':'activate','operation_mode':'offline_cash_only','license_duration_type':'permanent','iat':int(self.issued.timestamp())}
        code='OL1.'+base64.urlsafe_b64encode(json.dumps(grant).encode()).decode().rstrip('=')+'.unused'
        body={'schema':'sammoy.commissioning-response.v1','site_code':'site','post_no':1,'offline_code':code}
        signed={**body,'signature':base64.urlsafe_b64encode(self.private.sign(auth.canonical(body))).decode()}
        result=self.evaluate(self.row(raw_payload={'commissioning_authorization':signed},last_success_at=None))
        self.assertFalse(result['locked']);self.assertEqual(result['operation_mode'],'offline_cash_only')

    def test_new_signed_server_time_can_recover_a_bad_wall_clock(self):
        now=datetime.now(UTC);clock=auth.LicenseClock();clock.now(wall=now+timedelta(days=100));clock.reset(now)
        self.assertLess(clock.now(wall=now+timedelta(days=100)),now+timedelta(seconds=2))

class SignedSyncFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_network_sync_preserves_active_paid_session(self):
        helper=SignedLicenseTests();helper.setUp()
        try:
            runtime=WashRuntime();runtime._all_off_sync=Mock();runtime.state.update(creditSum=5000,_creditFloat=5000.0,activeMode='water',requestedOutput='water',phase='active')
            row=helper.row();conn=Mock();conn.execute.return_value.fetchone.return_value=row
            client=AsyncMock();client.__aenter__.return_value.post.side_effect=httpx.ConnectError('offline')
            with patch.object(main,'get_license_settings',return_value=helper.config),patch.object(main,'read_license_cache',return_value=row),patch.object(main,'wash_runtime',runtime),patch.object(main,'db') as db,patch.object(main,'sync_pending_offline_license_codes',AsyncMock()),patch.object(main.httpx,'AsyncClient',return_value=client):
                db.return_value.__enter__.return_value=conn
                result=await main.sync_license_once()
            self.assertFalse(result['ok']);self.assertFalse(result['license']['locked']);self.assertEqual(runtime.state['creditSum'],5000);self.assertEqual(runtime.state['activeMode'],'water');runtime._all_off_sync.assert_not_called()
        finally:helper.doCleanups()

class ClickAdmissionTests(unittest.TestCase):
    def test_new_click_is_blocked_without_gateway_but_no_licence_is_changed(self):
        from fastapi import HTTPException
        from app.connectivity import GatewayConnectivity
        monitor=GatewayConnectivity(offline_threshold=1,online_threshold=1)
        with patch.object(main,'gateway_connectivity',monitor):
            with self.assertRaises(HTTPException):main.require_click_gateway({'gateway_url':'https://gateway.test'})
            monitor.observe(gateway_url='https://gateway.test',success=True)
            main.require_click_gateway({'gateway_url':'https://gateway.test'})
            monitor.observe(gateway_url='https://gateway.test',success=False)
            with self.assertRaises(HTTPException):main.require_click_gateway({'gateway_url':'https://gateway.test'})
    def test_stale_or_wrong_gateway_health_is_not_accepted(self):
        from app.connectivity import GatewayConnectivity
        monitor=GatewayConnectivity();monitor.observe(gateway_url='https://gateway.test',success=True)
        self.assertFalse(monitor.available('https://other.test'))
        monitor.last_observed-=46;self.assertFalse(monitor.available('https://gateway.test'));self.assertFalse(monitor.snapshot()['internetOnline'])
