import unittest
from unittest.mock import AsyncMock,Mock,patch
from fastapi.testclient import TestClient
from app import main

class CustomerSetupGateTests(unittest.TestCase):
    def setUp(self):self.client=TestClient(main.app)
    def test_access_is_closed_until_explicitly_complete(self):
        for complete,code in ((False,403),(True,204)):
            with patch.object(main,'get_commissioning_state',return_value={'complete':complete}):
                response=self.client.get('/api/kiosk/access')
                self.assertEqual(response.status_code,code)
                if code==204:self.assertEqual(response.headers['cache-control'],'no-store')
    def test_uninstalled_modes_and_new_click_intents_are_rejected_before_side_effects(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch.object(main.wash_runtime,'select_mode') as select,patch.object(main,'apply_license_to_runtime') as license,patch.object(main,'db') as db:
            self.assertEqual(self.client.post('/api/wash/mode',json={'mode':'water'}).status_code,409)
            self.assertEqual(self.client.post('/api/click/intents',json={'amount_sum':10000}).status_code,409)
            select.assert_not_called();license.assert_not_called();db.assert_not_called()
    def test_pause_remains_available_before_setup_and_normal_modes_work_after_setup(self):
        with patch.object(main,'get_commissioning_state',return_value={'complete':False}),patch.object(main.wash_runtime,'select_mode',return_value={'ok':True}) as select:
            self.assertEqual(self.client.post('/api/wash/mode',json={'mode':'pause'}).status_code,200)
            select.assert_called_once_with('pause')
        with patch.object(main,'get_commissioning_state',return_value={'complete':True}),patch.object(main.wash_runtime,'select_mode',return_value={'ok':True}) as select:
            self.assertEqual(self.client.post('/api/wash/mode',json={'mode':'water'}).status_code,200)
            select.assert_called_once_with('water')
