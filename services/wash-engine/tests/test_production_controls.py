"""Production command guards: never run hardware or database operations."""
import unittest
from unittest.mock import patch,Mock,AsyncMock
from fastapi.testclient import TestClient
from app import main
from app.auth import current_user

class ProductionControlsTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(main.app)
        self.flag=patch.object(main.settings,'simulation_enabled',False);self.flag.start()
    def tearDown(self):
        self.flag.stop();main.app.dependency_overrides.clear()
    def login(self,role='admin',change=False):
        main.app.dependency_overrides[current_user]=lambda:{'role':role,'must_change_password':change,'login':role}
    def test_stop_requires_role_and_never_burns_money(self):
        with patch.object(main.wash_runtime,'stop_wash') as stop:
            self.assertEqual(self.client.post('/api/wash/stop').status_code,401)
            self.login('owner');self.assertEqual(self.client.post('/api/wash/stop').status_code,403)
            self.login(change=True);self.assertEqual(self.client.post('/api/wash/stop').status_code,428)
            self.login();self.assertEqual(self.client.post('/api/wash/stop').status_code,409)
            stop.assert_not_called()
    def test_production_rejects_all_simulation_writes_before_side_effects(self):
        self.login()
        paths=[('/api/wash/credit',{'amount_sum':1000,'source':'admin'}),
          ('/api/admin/wash/simulation/total-stop',{'active':True}),
          ('/api/admin/wash/simulation/coin-pulses',{'count':1}),
          ('/api/admin/wash/simulation/license',{'mode':'valid'}),
          ('/api/admin/io/simulate/input/total_stop',{'active':True}),
          ('/api/admin/io/simulate/pulses/bill_pulse',{'count':1}),
          ('/api/admin/io/simulate/rfid',{'uid':'7C212602'}),
          ('/api/admin/io/simulate/reset',{})]
        with patch.object(main,'wash_runtime') as runtime,patch.object(main,'io_request',new_callable=AsyncMock) as io:
            for path,body in paths:
                with self.subTest(path=path):self.assertEqual(self.client.post(path,json=body).status_code,403)
            self.assertEqual(runtime.mock_calls,[]);io.assert_not_called()
    def test_test_profile_still_requires_admin(self):
        with patch.object(main.settings,'simulation_enabled',True),patch.object(main.wash_runtime,'set_simulated_total_stop',return_value={'ok':True}) as setter:
            self.assertEqual(self.client.post('/api/admin/wash/simulation/total-stop',json={'active':True}).status_code,401)
            self.login('owner');self.assertEqual(self.client.post('/api/admin/wash/simulation/total-stop',json={'active':True}).status_code,403)
            self.login();self.assertEqual(self.client.post('/api/admin/wash/simulation/total-stop',json={'active':True}).status_code,200)
            setter.assert_called_once_with(True)
    def test_disabling_overrides_is_available_in_production(self):
        self.login()
        with patch.object(main.wash_runtime,'reset_simulation'),patch.object(main,'apply_license_to_runtime'),patch.object(main.wash_runtime,'snapshot',return_value={'ok':True}):
            self.assertEqual(self.client.post('/api/admin/wash/simulation/reset').status_code,200)
