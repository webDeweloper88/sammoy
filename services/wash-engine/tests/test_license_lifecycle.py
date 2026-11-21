import unittest
from datetime import datetime,UTC,timedelta
from unittest.mock import Mock
import test_wash_logic
from app.license_lifecycle import idle,receipt,BUSY
from app.wash_logic import WashRuntime
from app.main import evaluate_license_lock
from test_offline_operation import OfflineOperationTests

class LicenseLifecycleTests(unittest.TestCase):
    def test_ack_only_after_zero_balance_and_confirmed_off(self):
        state={'outputsOffConfirmed':True,'licenseRetirementPending':True,'licenseLocked':True,'license':{'lifecycle':{'revision':7}}}
        self.assertEqual(receipt(state)['lifecycle_ack_revision'],7)
        for key in BUSY:
            busy={**state,key:1}
            self.assertFalse(idle(busy),key);self.assertIsNone(receipt(busy)['lifecycle_ack_revision'],key)
        self.assertIsNone(receipt({**state,'outputsOffConfirmed':False})['lifecycle_ack_revision'])
    def test_existing_credit_is_preserved_until_idle_then_blocks(self):
        r=WashRuntime();r._all_off_sync=Mock();r.state.update(creditSum=1000,_creditFloat=1000.0,outputsOffConfirmed=True,activeMode='water',requestedOutput='water')
        payload={'lifecycle':{'state':'revocation_pending','revision':4}}
        r.set_license_status(False,'pending',payload)
        self.assertEqual(r.state['creditSum'],1000);self.assertEqual(r.state['activeMode'],'water')
        self.assertFalse(r.state['licenseLocked']);r._all_off_sync.assert_not_called()
        with self.assertRaises(ValueError):r.add_credit(1000,source='click')
        r.state.update(creditSum=0,_creditFloat=0.0,activeSessionId=None,activeMode=None,armedMode=None,requestedOutput=None)
        r.set_license_status(False,'pending',payload)
        self.assertTrue(r.state['licenseLocked']);r._all_off_sync.assert_called_once()
        self.assertEqual(receipt(r.state)['lifecycle_ack_revision'],4)
    def test_paid_dry_fog_program_finishes_before_retirement_ack(self):
        from test_dry_fog_runtime import DryFogRuntimeTests
        helper=DryFogRuntimeTests();r=helper.runtime(1000)
        r.state['outputsOffConfirmed']=True
        r.select_mode('aroma_1');helper.tick(r,100.2)
        payload={'lifecycle':{'state':'revocation_pending','revision':9}}
        r.set_license_status(False,'pending',payload)
        self.assertEqual(r.last_output,'aroma_1')
        self.assertIsNone(receipt(r.state)['lifecycle_ack_revision'])
        helper.tick(r,101.2)
        self.assertEqual(r.state['creditSum'],0);self.assertIsNone(r.last_output)
        r.set_license_status(False,'pending',payload)
        self.assertTrue(r.state['licenseLocked'])
        self.assertEqual(receipt(r.state)['lifecycle_ack_revision'],9)

    def test_online_cache_cannot_extend_lease_on_network_failure(self):
        row=OfflineOperationTests().row(raw_payload={'operation_mode':'online','online_lease_until':(datetime.now(UTC)-timedelta(seconds=1)).isoformat()})
        self.assertTrue(evaluate_license_lock(row,{'enabled':True})['locked'])
        row['raw_payload']['online_lease_until']=(datetime.now(UTC)+timedelta(hours=1)).isoformat()
        self.assertFalse(evaluate_license_lock(row,{'enabled':True})['locked'])
        row['raw_payload']={'operation_mode':'online'}
        self.assertTrue(evaluate_license_lock(row,{'enabled':True})['locked'])
        row['raw_payload']={'operation_mode':'offline_cash_only'}
        self.assertFalse(evaluate_license_lock(row,{'enabled':True})['locked'])
