"""Loss of internet alone must not stop an already activated local controller."""
import unittest
from datetime import UTC,datetime,timedelta
from unittest.mock import patch
from fastapi import HTTPException
from app.main import evaluate_license_lock,require_click_ready

class OfflineOperationTests(unittest.TestCase):
    def row(self,**changes):
        now=datetime.now(UTC)
        return {'enabled':True,'locked':False,'state':'valid','reason':'valid','site_code':'SITE',
            'post_no':1,'machine_id':'test','days_left':None,'valid_until':None,
            'last_success_at':now-timedelta(days=60),'last_attempt_at':now,'next_sync_at':now,
            'grace_until':now-timedelta(days=50),'last_error':'network unavailable','raw_payload':{},**changes}
    def test_permanent_cached_license_survives_long_internet_outage(self):
        result=evaluate_license_lock(self.row(),{'enabled':True})
        self.assertFalse(result['locked']);self.assertEqual(result['state'],'grace')
    def test_time_limited_cached_license_keeps_its_actual_expiration(self):
        self.assertFalse(evaluate_license_lock(self.row(valid_until=datetime.now(UTC)+timedelta(days=1)),{'enabled':True})['locked'])
        self.assertTrue(evaluate_license_lock(self.row(valid_until=datetime.now(UTC)-timedelta(seconds=1)),{'enabled':True})['locked'])
    def test_known_disabled_license_does_not_become_valid_offline(self):
        self.assertTrue(evaluate_license_lock(self.row(enabled=False),{'enabled':True})['locked'])
        self.assertTrue(evaluate_license_lock(self.row(raw_payload={'locked':True}),{'enabled':True})['locked'])
    def test_offline_does_not_replace_first_activation(self):
        self.assertTrue(evaluate_license_lock(self.row(last_success_at=None),{'enabled':True})['locked'])
        self.assertTrue(evaluate_license_lock(None,{'enabled':True})['locked'])
    def test_permanent_offline_cash_license_cannot_create_click_payments(self):
        with patch('app.main.read_license_cache',return_value=self.row(raw_payload={'operation_mode':'offline_cash_only'})):
            with self.assertRaises(HTTPException):require_click_ready({'enabled':True})
