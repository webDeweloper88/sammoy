import unittest
from unittest.mock import Mock, patch
import test_wash_logic
from app.hardware_status import HardwareFault, critical_code, peripheral_status
from app.io_safety import OUTPUTS

class HardwareStatusTests(unittest.TestCase):
    def io(self):
        return {'inputs':{'total_stop':True},'modbus_ok':True,'poll_age_seconds':0,
                'outputs':dict.fromkeys(OUTPUTS,False),'nv9_pulses':0,
                'nv9_enabled':True,'nv9_listener_alive':True,'bill_filter':{'ready':True}}

    def test_paid_wash_continues_with_each_peripheral_failure(self):
        for cash, nfc in ((False,True),(True,False),(False,False)):
            with self.subTest(cash=cash,nfc=nfc):
                r=test_wash_logic.WashLogicTests().runtime(total_stop=True)
                r.state.update(creditSum=10000,_creditFloat=10000.0)
                r.select_mode('water')
                io=self.io();io['nv9_listener_alive']=cash
                r._get_io_sync.return_value=io
                r._get_rfid_events_sync.return_value={'rfid':{'online':nfc}}
                r.tick()
                self.assertTrue(r.state['lastIoOk'])
                self.assertEqual(r.state['activeMode'],'water')
                self.assertEqual(r.state['billInputReady'],cash)
                self.assertEqual(r.state['nfcReady'],nfc)
                self.assertEqual(set(r.state['hardwareWarnings']),set(([] if cash else ['cash_unavailable'])+([] if nfc else ['nfc_unavailable'])))
                self.assertIsNone(r.state['hardwareErrorCode'])

    def test_nfc_http_failure_is_warning_not_control_fault(self):
        r=test_wash_logic.WashLogicTests().runtime(total_stop=True)
        r.state.update(creditSum=10000,_creditFloat=10000.0);r.select_mode('water')
        r._get_io_sync.return_value=self.io()
        r._get_rfid_events_sync.side_effect=RuntimeError('NFC timeout')
        r.tick()
        self.assertEqual(r.state['activeMode'],'water')
        self.assertIn('nfc_unavailable',r.state['hardwareWarnings'])

    def test_connection_loss_keeps_credit_and_never_resumes(self):
        r=test_wash_logic.WashLogicTests().runtime(total_stop=True)
        r.state.update(creditSum=10000,_creditFloat=10000.0);r.select_mode('water')
        r._get_io_sync.return_value={**self.io(),'modbus_ok':False}
        with self.assertRaises(RuntimeError):r.tick()
        self.assertEqual(r.state['hardwareErrorCode'],'io_connection_lost')
        self.assertEqual(r.state['creditSum'],10000)
        r._all_off_sync.assert_called()
        r._get_io_sync.return_value=self.io();r.tick()
        self.assertIsNone(r.state['armedMode']);self.assertIsNone(r.state['requestedOutput'])
        self.assertEqual(r.state['creditSum'],10000)

    def test_helper_http_failure_has_specific_code_and_stops(self):
        r=test_wash_logic.WashLogicTests().runtime(total_stop=True)
        r.state.update(creditSum=10000,_creditFloat=10000.0);r.select_mode('water')
        r._get_io_sync.side_effect=HardwareFault('io_helper_unavailable','connection refused')
        with self.assertRaises(HardwareFault):r.tick()
        self.assertEqual(r.state['hardwareErrorCode'],'io_helper_unavailable')
        self.assertIsNone(r.state['armedMode']);self.assertEqual(r.state['creditSum'],10000)
        r._all_off_sync.assert_called()

    def test_filter_fault_blocks_cash_and_recovers_independently(self):
        io=self.io();io['bill_filter']={'ready':True,'fault':'stuck_active'}
        s=peripheral_status(io,{'rfid':{'online':True}})
        self.assertFalse(s['billInputReady']);self.assertTrue(s['nfcReady'])
        io['bill_filter']['fault']=None
        self.assertEqual(peripheral_status(io,{'rfid':{'online':True}})['hardwareWarnings'],[])

    def test_accounting_faults_remain_critical(self):
        self.assertEqual(critical_code(RuntimeError('NV9 journal counter moved backwards')),'payment_accounting_error')
        self.assertEqual(critical_code(RuntimeError('Output readback is incomplete')),'output_confirmation_failed')
        self.assertEqual(critical_code(RuntimeError('I/O polling is stale')),'io_data_stale')

    def test_cash_accounting_database_failure_is_not_silenced(self):
        r=test_wash_logic.WashLogicTests().runtime(total_stop=True)
        r.state.update(creditSum=10000,_creditFloat=10000.0);r.select_mode('water')
        r._get_io_sync.return_value=self.io()
        with patch('app.cash_ingest.capture',side_effect=RuntimeError('database unavailable')):
            with self.assertRaises(HardwareFault):r.tick()
        self.assertEqual(r.state['hardwareErrorCode'],'payment_accounting_error')
        self.assertEqual(r.state['creditSum'],10000);self.assertIsNone(r.state['armedMode'])
        r._all_off_sync.assert_called()

    def test_listener_failure_does_not_skip_durable_capture(self):
        r=test_wash_logic.WashLogicTests().runtime(total_stop=True)
        io=self.io();io['nv9_listener_alive']=False
        r._get_io_sync.return_value=io
        with patch('app.cash_ingest.capture') as capture:
            r.tick()
            capture.assert_called_once_with(r,io,recover=True)
        self.assertIn('cash_unavailable',r.state['hardwareWarnings'])
