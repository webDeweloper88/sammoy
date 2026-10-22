import unittest
import threading
from unittest.mock import Mock,patch
import test_wash_logic
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import current_user
from app import admin_api

class BillInputAdminTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();app.include_router(admin_api.router);self.app=app;self.client=TestClient(app)
    def test_only_admin_may_read_or_configure_filter(self):
        for path in ('/api/admin/service/bill-filter','/api/admin/service/bill-filter/reset'):
            self.assertEqual(self.client.post(path,json={}).status_code,401)
            self.app.dependency_overrides[current_user]=lambda:{'role':'owner','login':'owner','must_change_password':False}
            self.assertEqual(self.client.post(path,json={}).status_code,403)
            self.app.dependency_overrides.clear()
    def test_money_session_prevents_changes_or_fault_reset(self):
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
        runtime=Mock(lock=threading.RLock(),snapshot=Mock(return_value={'state':{'creditSum':11000}}))
        with patch.object(admin_api,'wash_runtime',runtime),patch('app.admin_service.io_sync') as io:
            for path in ('/api/admin/service/bill-filter','/api/admin/service/bill-filter/reset'):
                self.assertEqual(self.client.post(path,json={}).status_code,409)
            io.assert_not_called()
    def test_idle_save_is_forwarded_and_audited_without_touching_money(self):
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
        runtime=Mock(lock=threading.RLock(),snapshot=Mock(return_value={'state':{'creditSum':0}}))
        with patch.object(admin_api,'wash_runtime',runtime),patch('app.admin_service.io_sync',return_value={'ready':False,'settings':{'min_pulse_ms':20}}) as io,patch.object(admin_api,'audit') as audit:
            response=self.client.post('/api/admin/service/bill-filter',json={'min_pulse_ms':20})
            self.assertEqual(response.status_code,200)
            self.assertEqual(io.call_args.args[-1],{'min_pulse_ms':20});audit.assert_called_once()
            runtime.add_credit.assert_not_called()
