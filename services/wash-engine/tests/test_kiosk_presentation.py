import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app.wash_logic import WashRuntime
from app.main import kiosk_payment_options

class KioskPresentationTests(unittest.TestCase):
    def test_time_requires_program_and_uses_program_tariff(self):
        r=WashRuntime();r.state['creditSum']=25000
        self.assertIsNone(r.snapshot()['state']['remainingSeconds'])
        r.state['armedMode']='water'
        self.assertEqual(r.snapshot()['state']['remainingSeconds'],1000)
        r.state['activeMode']='foam'
        self.assertEqual(r.snapshot()['state']['remainingSeconds'],500)
        self.assertNotIn('remainingSeconds',r.state)
        self.assertEqual(r.state['creditSum'],25000)

    def test_pause_projection_uses_shared_remaining_budget_and_paid_tariff(self):
        r=WashRuntime();r.state.update(creditSum=1000,armedMode='water',pauseState='free',freePauseRemaining=17)
        self.assertEqual(r.snapshot()['state']['remainingSeconds'],17)
        self.assertEqual(r.snapshot()['state']['displayTimeKind'],'free_pause')
        r.state['pauseState']='paid'
        self.assertEqual(r.snapshot()['state']['remainingSeconds'],120)
        self.assertEqual(r.snapshot()['state']['displayTimeKind'],'paid_pause')
        self.assertEqual(r.state['freePauseRemaining'],17)

    def test_zero_or_free_tariff_never_divides_by_zero(self):
        r=WashRuntime();r.state.update(creditSum=1000,armedMode='water')
        r.params['tariffs']['water']['amountSum']=0
        self.assertIsNone(r.snapshot()['state']['remainingSeconds'])
        r.state.update(pauseState='paid');r.params['paidPause']['amountSum']=0
        self.assertIsNone(r.snapshot()['state']['remainingSeconds'])

    def test_payment_options_do_not_expose_tokens(self):
        config={'min_amount_sum':1000,'max_amount_sum':100000,'site_token':'secret','gateway_url':'private'}
        with patch('app.main.get_click_settings',return_value=config),patch('app.main.require_click_ready'):
            self.assertEqual(kiosk_payment_options(),{'ok':True,'click':{'enabled':True,'minAmount':1000,'maxAmount':100000}})
        with patch('app.main.get_click_settings',return_value=config),patch('app.main.require_click_ready',side_effect=HTTPException(409)):
            self.assertFalse(kiosk_payment_options()['click']['enabled'])
