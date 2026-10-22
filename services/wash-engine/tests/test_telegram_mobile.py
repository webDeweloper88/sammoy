import asyncio
import base64
import unittest
from unittest.mock import AsyncMock,Mock,patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from app import main,telegram_mobile as mobile

class TelegramMobileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mobile.SESSIONS.clear()
        self.guard=patch.object(mobile,'guard',return_value='site-scope');self.guard.start();self.addCleanup(self.guard.stop)
        self.report=patch.object(main,'telegram_setup_request',AsyncMock(return_value={'owner_paired':False,'configured':False}));self.request=self.report.start();self.addCleanup(self.report.stop)
        self.network=patch('app.admin_api.network_request',AsyncMock(return_value={'interfaces':[{'interface':'eth0','connected':True,'address':'10.10.10.8'},{'interface':'wlan0','connected':True,'address':'192.168.43.25'}]}));self.network.start();self.addCleanup(self.network.stop)
    async def issue(self,interface='eth0'):
        created=await mobile.create_session(mobile.PhoneSession(interface=interface,language='uz'))
        return created,created['mobile_url'].rsplit('/',1)[1]
    async def test_phone_url_uses_selected_real_interface_not_request_host(self):
        created,raw=await self.issue('wlan0')
        self.assertTrue(created['mobile_url'].startswith('http://192.168.43.25/'))
        self.assertIn(b'<svg',base64.b64decode(created['qr_data_url'].split(',')[1]))
        self.assertNotIn(raw,mobile.SESSIONS)
        response=await mobile.phone_page(raw)
        self.assertIn('no-store',response.headers['cache-control']);self.assertIn('frame-ancestors',response.headers['content-security-policy']);self.assertIn('no-referrer',response.headers['referrer-policy']);self.assertIn(b'lang="uz"',response.body)
    async def test_link_single_use_and_returns_no_token(self):
        _,raw=await self.issue()
        with patch.object(main,'commissioning_telegram_action',AsyncMock(return_value={'bot_username':'test_bot','secret':'never-return'})) as configure:
            result=await mobile.phone_configure(raw,mobile.PhoneToken(token='test-token'))
            self.assertEqual(result,{'ok':True,'bot_username':'test_bot'});configure.assert_awaited_once_with('configure-auto',{'token':'test-token'})
        with self.assertRaises(HTTPException) as e:await mobile.phone_page(raw)
        self.assertEqual(e.exception.status_code,410)
    async def test_expired_rotated_and_wrong_site_links_fail(self):
        _,old=await self.issue();_,raw=await self.issue()
        for cap,scope in ((old,'site-scope'),(raw,'other-site')):
            with self.assertRaises(HTTPException):mobile.lookup(cap,scope)
        _,raw=await self.issue()
        with patch.object(mobile.time,'time',return_value=10**12):
            with self.assertRaises(HTTPException):await mobile.phone_page(raw)
    async def test_failed_token_can_retry_but_is_limited(self):
        _,raw=await self.issue()
        with patch.object(main,'commissioning_telegram_action',AsyncMock(side_effect=HTTPException(400,'Invalid token'))) as configure:
            for _ in range(5):
                with self.assertRaises(HTTPException) as error:await mobile.phone_configure(raw,mobile.PhoneToken(token='bad-token'))
                self.assertEqual(error.exception.status_code,400)
            with self.assertRaises(HTTPException) as error:await mobile.phone_configure(raw,mobile.PhoneToken(token='bad-token'))
            self.assertEqual(error.exception.status_code,410);self.assertEqual(configure.await_count,5)
    async def test_concurrent_submit_and_rotation_are_blocked(self):
        _,raw=await self.issue();_,value=mobile.lookup(raw,'site-scope');value['busy']=True
        with self.assertRaises(HTTPException) as error:await mobile.phone_configure(raw,mobile.PhoneToken(token='token'))
        self.assertEqual(error.exception.status_code,409)
        with self.assertRaises(HTTPException):await self.issue()
    async def test_unavailable_interface_and_paired_bot_are_rejected(self):
        self.network.stop()
        with patch('app.admin_api.network_request',AsyncMock(return_value={'interfaces':[]})):
            with self.assertRaises(HTTPException):await self.issue()
        self.request.return_value={'owner_paired':True}
        with self.assertRaises(HTTPException):await self.issue()
    async def test_phone_cannot_replace_already_configured_bot(self):
        _,raw=await self.issue();self.request.return_value={'configured':True}
        with patch.object(main,'commissioning_telegram_action',AsyncMock()) as configure:
            with self.assertRaises(HTTPException):await mobile.phone_configure(raw,mobile.PhoneToken(token='token'))
            configure.assert_not_awaited()
    async def test_session_route_is_reachable_in_full_application(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}):
            result=TestClient(main.app).post('/api/commissioning/telegram/mobile/session',json={'interface':'eth0'},headers={'X-Commissioning-Client-IP':'10.10.10.20'})
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.json()['mobile_url'].startswith('http://10.10.10.8/'))
    async def test_creation_requires_existing_commissioning_access(self):
        app=FastAPI();app.include_router(mobile.router)
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}):
            response=TestClient(app).post('/api/commissioning/telegram/mobile/session',json={'interface':'eth0'})
            self.assertEqual(response.status_code,403)

class TelegramMobileGuardTests(unittest.TestCase):
    def test_complete_funded_backup_and_locked_posts_are_rejected(self):
        for complete,credit,local,locked in ((True,0,1,False),(False,1000,1,False),(False,0,2,False),(False,0,1,True)):
            with self.subTest(complete=complete,credit=credit,local=local,locked=locked),patch.object(main,'get_commissioning_state',return_value={'complete':complete}),patch.object(main.wash_runtime,'snapshot',return_value={'state':{'creditSum':credit}}),patch('app.wallet_api.configuration',return_value={'enabled':True,'primary_post':1}),patch.object(main,'get_license_settings',return_value={'site_code':'s','post_no':local}),patch.object(main,'apply_license_to_runtime',return_value={'locked':locked}):
                with self.assertRaises(HTTPException):mobile.guard()
