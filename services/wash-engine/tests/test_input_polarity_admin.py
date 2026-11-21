import unittest,threading
from unittest.mock import Mock,patch
import test_wash_logic
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import current_user
from app import admin_api

class InputPolarityAdminTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI();self.app.include_router(admin_api.router);self.client=TestClient(self.app)
    def admin(self):
        self.app.dependency_overrides[current_user]=lambda:{'role':'admin','login':'admin','must_change_password':False}
    def post(self,value=False):return self.client.post('/api/admin/service/input-polarity',json={'active_low':value})
    def test_auth_and_validation(self):
        self.assertEqual(self.post().status_code,401)
        self.app.dependency_overrides[current_user]=lambda:{'role':'owner','must_change_password':False}
        self.assertEqual(self.post().status_code,403)
        self.admin();self.assertEqual(self.post('false').status_code,422)
    def test_all_live_session_states_block_change(self):
        self.admin()
        for state in ({'creditSum':1},{'activeMode':'water'},{'armedMode':'foam'},{'activeSessionId':1},{'walletTransferPending':True}):
            r=Mock(device_type='wash',lock=threading.RLock(),snapshot=Mock(return_value={'state':state}))
            with patch.object(admin_api,'wash_runtime',r),patch('app.admin_service.io_sync') as io:
                self.assertEqual(self.post().status_code,409);io.assert_not_called()
    def test_idle_change_is_audited_and_only_targets_inputs(self):
        self.admin();r=Mock(device_type='wash',lock=threading.RLock(),snapshot=Mock(return_value={'state':{'creditSum':0}}))
        with patch.object(admin_api,'wash_runtime',r),patch('app.admin_service.io_sync',return_value={'ok':True}) as io,patch.object(admin_api,'audit') as audit:
            self.assertEqual(self.post().status_code,200)
            self.assertEqual(io.call_args.args[-2:],('/inputs/polarity',{'active_low':False}))
            audit.assert_called_once();r.add_credit.assert_not_called()
