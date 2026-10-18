import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import current_user

class AdminAuthTests(unittest.TestCase):
    def tearDown(self):app.dependency_overrides.clear()
    def requests(self,expected):
        client=TestClient(app)
        for method,path,body in [('GET','service/storage',None),('GET','service/click-payments',None),('GET','diagnostics',None),('GET','network/status',None),('POST','network/apply',{}),('POST','service/all-off',None),('POST','service/outputs/water/test',{'confirmation':'water'}),('POST','service/money-input',{'bill_pulse_sum':1000}),('GET','service/events',None)]:
            with self.subTest(path=path):self.assertEqual(client.request(method,'/api/admin/'+path,json=body).status_code,expected)
    def test_missing_login(self):self.requests(401)
    def test_owner_cannot_use_admin(self):
        app.dependency_overrides[current_user]=lambda:{'role':'owner','must_change_password':False}
        self.requests(403)
    def test_first_password_change_is_required(self):
        app.dependency_overrides[current_user]=lambda:{'role':'admin','must_change_password':True}
        self.requests(428)
    def test_admin_cannot_open_owner_business_endpoints(self):
        app.dependency_overrides[current_user]=lambda:{'role':'admin','must_change_password':False}
        client=TestClient(app)
        for path in ['/api/owner/wash/parameters','/api/owner/vip-profiles','/api/owner/rfid/cards','/api/owner/telegram-setup/status']:
            self.assertEqual(client.get(path).status_code,403,path)
        self.assertEqual(client.post('/api/kiosk/settings',json={'config':{}}).status_code,403)
