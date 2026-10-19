import unittest
import threading
from datetime import datetime,UTC
from unittest.mock import patch
from fastapi import HTTPException
from app import owner_site,site_reporting

class SiteTests(unittest.TestCase):
    def test_tashkent_bounds_and_one_year_limit(self):
        a,b=site_reporting.bounds('2026-10-19','2026-10-19')
        self.assertEqual(a,datetime(2026,10,18,19,tzinfo=UTC))
        self.assertEqual((b-a).total_seconds(),86400)
        for a,b in [('bad','2026-10-19'),('2026-10-19','2026-10-18'),('2024-01-01','2026-01-01')]:
            with self.assertRaises(HTTPException):site_reporting.bounds(a,b)

    def test_aggregate_excludes_unavailable_and_old_totals(self):
        report={'summary':dict.fromkeys(site_reporting.TOTALS,0),'modes':[],'timeline':[]}
        report['summary'].update(cash_sum=10000,click_sum=25000,receipts_sum=35000,customer_saved_sum=50000,customer_used_sum=50000,bonus_granted_sum=3500,test_credit_sum=100000)
        result=site_reporting.aggregate([{'status':'online','report':report},{'status':'offline','report':report}])
        self.assertEqual(result['summary']['receipts_sum'],35000)
        self.assertFalse(result['complete']);self.assertEqual(result['online_posts'],1)

    def test_generation_and_primary_fence_before_remote_write(self):
        cfg={'generation':2,'primary_post':1,'local_post':2}
        with patch.object(owner_site,'settings_write') as write:
            for sender,generation in [(1,1),(2,2),(3,2)]:
                with self.assertRaises(HTTPException):owner_site.internal({'action':'write','generation':generation},cfg,sender)
            write.assert_not_called()

    def test_peer_identity_is_verified(self):
        with patch('app.wallet_api.rpc',return_value={'post_no':3}):
            with self.assertRaises(HTTPException):owner_site.peer_call({'local_post':1,'generation':1},2,{'action':'read'})

    def test_standby_cannot_change_remote_settings(self):
        cfg={'enabled':True,'local_post':2,'primary_post':1}
        with patch.object(owner_site,'target',return_value=cfg),patch.object(owner_site,'peer_call') as call:
            with self.assertRaises(HTTPException):owner_site.write_settings(1,'parameters',owner_site.SettingsChange(expected_revision='a'*64,value={}),{'login':'owner'})
            call.assert_not_called()

    def test_no_confirmation_after_timeout(self):
        cfg={'enabled':True,'local_post':1,'primary_post':1}
        with patch.object(owner_site,'target',return_value=cfg),patch.object(owner_site,'peer_call',side_effect=TimeoutError):
            with self.assertRaises(HTTPException) as result:owner_site.write_settings(2,'parameters',owner_site.SettingsChange(expected_revision='a'*64,value={}),{'login':'owner'})
            self.assertEqual(result.exception.status_code,503)

    def test_revisions_ignore_dictionary_order(self):
        self.assertEqual(owner_site.revision({'a':1,'b':2}),owner_site.revision({'b':2,'a':1}))
        self.assertNotEqual(owner_site.revision({'a':1}),owner_site.revision({'a':2}))

    def test_settings_conflict_prevents_overwriting_other_owner(self):
        from unittest.mock import Mock
        runtime=Mock(lock=threading.RLock(),snapshot=Mock(return_value={'state':{}}))
        with patch('app.main.wash_runtime',runtime),patch.object(owner_site,'settings_read',return_value={'revision':'b'*64}),patch('app.main.owner_save_wash_parameters') as save:
            with self.assertRaises(HTTPException) as result:owner_site.settings_write('parameters',{'expected_revision':'a'*64,'value':{}},'owner')
            self.assertEqual(result.exception.status_code,409);save.assert_not_called()

    def test_no_internet_does_not_disable_local_snapshot_or_reports(self):
        from unittest.mock import Mock
        runtime=Mock(device_type='dry_fog',snapshot=Mock(return_value={'state':{'lastIoOk':True,'creditSum':11000}}))
        with patch('app.main.wash_runtime',runtime),patch('app.main.get_click_settings',return_value={'enabled':True}),patch('app.main.require_click_ready'),patch('app.main.gateway_connectivity.snapshot',return_value={'internetOnline':False}),patch('app.device_setup.local_status',return_value={'requested':{'display_name':'AROMA'}}),patch.object(owner_site,'local_report',return_value={'summary':{'cash_sum':10000}}),patch('httpx.Client',side_effect=AssertionError('Local report attempted external HTTP')):
            r=owner_site.local_snapshot(None,None)
            self.assertEqual(r['state']['creditSum'],11000);self.assertEqual(r['click'],'offline')
            self.assertEqual(r['report']['summary']['cash_sum'],10000)

    def test_owner_panel_rejects_admin_and_anonymous_access(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.auth import current_user
        app=FastAPI();app.include_router(owner_site.router)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/owner/site/overview').status_code,401)
            app.dependency_overrides[current_user]=lambda:{'role':'admin','must_change_password':False}
            self.assertEqual(client.get('/api/owner/site/overview').status_code,403)

    def test_standby_cannot_replace_site_telegram_configuration(self):
        import asyncio
        from app.main import owner_telegram_action
        from unittest.mock import AsyncMock
        with patch('app.wallet_api.configuration',return_value={'enabled':True,'local_post':2,'primary_post':1}),patch('app.main.telegram_setup_request',new_callable=AsyncMock) as setup:
            with self.assertRaises(HTTPException):asyncio.run(owner_telegram_action('disable',{}, {'login':'owner'}))
            setup.assert_not_awaited()

    def test_signed_owner_reports_do_not_take_wallet_control_lock(self):
        from app.wallet_api import internal,signature
        import time
        cfg={'enabled':True,'site_id':'TEST','peer_urls':{'1':'http://10.0.0.1'},'generation':1,'local_post':2,'primary_post':1}
        body={'site_id':'TEST','timestamp':int(time.time()),'sender_post':1,'payload':{'generation':1,'action':'snapshot'}}
        class NoLock:
            def __enter__(self):raise AssertionError('Report entered wallet control lock')
        with patch('app.wallet_api.configuration',return_value=cfg),patch('app.wallet_api.identity',return_value={'site_token':'test-secret'}),patch('app.wallet_api.control_lock',NoLock()),patch.object(owner_site,'internal',return_value={'ok':True,'post_no':2}):
            result=internal('owner-site',body,signature('test-secret','/api/wallet/internal/owner-site',body),None)
            self.assertEqual(result.status_code,200)
