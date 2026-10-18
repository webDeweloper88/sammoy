import unittest
from unittest.mock import Mock
from fastapi import HTTPException
import main
from controller_lease import ControllerLease

class OutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.controller=Mock();self.controller.output_map={'water':0}
        self.controller.read_outputs.return_value=[False]
        self.controller.confirmed_outputs_off.return_value=[False]*8
        self.controller.cfg={'outputs':[{'name':'water','address':0}]}
        main.APP_STATE.update(controller=self.controller,lease=ControllerLease())
        main.io_state['modbus_ok']=True
        main.output_test.active=None
    def test_expired_lease_rejects_on_but_allows_off(self):
        with self.assertRaises(HTTPException) as caught:main.set_output('water',main.OutputCommand(on=True))
        self.assertEqual(caught.exception.status_code,409)
        self.controller.write_output.assert_not_called()
        self.controller.write_output.return_value=False
        self.assertFalse(main.set_output('water',main.OutputCommand(on=False))['actual'])
    def test_readback_failure_forces_off(self):
        main.APP_STATE['lease'].heartbeat()
        self.controller.write_output.return_value=False
        with self.assertRaises(HTTPException):main.set_output('water',main.OutputCommand(on=True))
        self.controller.confirmed_outputs_off.assert_called_once();self.controller.all_outputs_off.assert_called_once()
        self.assertFalse(main.io_state['modbus_ok'])
    def test_all_off_attempts_every_relay(self):
        controller=main.ModbusController.__new__(main.ModbusController)
        controller.output_names=['water','foam','air']
        controller.write_output=Mock(side_effect=[RuntimeError('broken'),False,False])
        with self.assertRaises(RuntimeError):controller.all_outputs_off()
        self.assertEqual(controller.write_output.call_count,3)

class FastOffTests(unittest.TestCase):
    def controller(self,raw):
        c=main.ModbusController.__new__(main.ModbusController)
        c.output_names=['n'+str(i) for i in range(8)];c.output_map={name:i for i,name in enumerate(c.output_names)}
        c.read_outputs=Mock(return_value=raw);c.write_output=Mock();c.all_outputs_off=Mock();return c
    def test_idle_board_does_not_write_eight_redundant_commands(self):
        c=self.controller([False]*8);self.assertEqual(c.confirmed_outputs_off(),[False]*8)
        c.read_outputs.assert_called_once();c.write_output.assert_not_called()
    def test_transition_switches_only_active_relay_and_verifies_off(self):
        c=self.controller(None);c.read_outputs.side_effect=[[False,False,False,True,False,False,False,False],[False]*8]
        self.assertEqual(c.confirmed_outputs_off(),[False]*8);c.write_output.assert_called_once_with('n3',False);self.assertEqual(c.read_outputs.call_count,2)
    def test_multiple_active_relays_all_switched_off(self):
        c=self.controller(None);c.read_outputs.side_effect=[[True,False,True,False,False,False,False,False],[False]*8]
        c.confirmed_outputs_off();self.assertEqual([a.args for a in c.write_output.call_args_list],[('n0',False),('n2',False)])
    def test_short_or_failed_read_forces_exhaustive_shutdown(self):
        for raw in [[],[False]*7]:
            c=self.controller(raw)
            with self.assertRaises(RuntimeError):c.confirmed_outputs_off()
            c.all_outputs_off.assert_called_once()
    def test_failed_write_never_returns_confirmed_off(self):
        c=self.controller([True]+[False]*7);c.write_output.side_effect=RuntimeError('timeout')
        with self.assertRaises(RuntimeError):c.confirmed_outputs_off()
        c.all_outputs_off.assert_called_once()
    def test_stuck_relay_never_returns_confirmed_off(self):
        c=self.controller([True]+[False]*7)
        with self.assertRaises(RuntimeError):c.confirmed_outputs_off()
        c.all_outputs_off.assert_called_once()
    def test_endpoint_returns_fresh_proof_and_needs_no_lease_for_off(self):
        c=Mock();c.cfg={'outputs':[{'name':'n'+str(i),'address':i} for i in range(8)]};c.confirmed_outputs_off.return_value=[False]*8;c.read_outputs.return_value=[False]*8
        main.APP_STATE.update(controller=c,lease=ControllerLease())
        result=main.controller_all_off();self.assertTrue(result['off_confirmed']);self.assertEqual(len(result['outputs']),8)

class OptionalCashTests(unittest.TestCase):
    def test_disabled_acceptor_never_opens_gpio(self):
        from unittest.mock import patch
        with patch.object(main.gpiod,'chip') as chip:
            main.nv9_listener({'bill_acceptor':{'enabled':False}},Mock(),Mock())
            chip.assert_not_called()


class SerialReconnectTests(unittest.TestCase):
    def controller(self):
        return main.ModbusController({'transport':{'device':'/dev/test','baud_rate':9600,'data_bits':8,'stop_bits':1,'response_timeout_ms':100,'slave_address':1},'outputs':[]})
    def test_reconnect_releases_previous_serial_owner_before_opening(self):
        from unittest.mock import patch
        controller=self.controller();old=Mock();controller.client=old
        replacement=Mock();replacement.connect.return_value=True
        def construct(**kwargs):
            old.close.assert_called_once()
            return replacement
        with patch.object(main,'ModbusSerialClient',side_effect=construct):
            self.assertTrue(controller.connect())
        self.assertIs(controller.client,replacement)
        controller.close();replacement.close.assert_called_once();self.assertIsNone(controller.client)
    def test_failed_connect_closes_transport_and_next_attempt_recovers(self):
        from unittest.mock import patch
        for failure in [False,RuntimeError('unplugged')]:
            controller=self.controller();bad=Mock();good=Mock();good.connect.return_value=True
            if failure is False:bad.connect.return_value=False
            else:bad.connect.side_effect=failure
            with patch.object(main,'ModbusSerialClient',side_effect=[bad,good]):
                if failure is False:self.assertFalse(controller.connect())
                else:
                    with self.assertRaises(RuntimeError):controller.connect()
                bad.close.assert_called_once();self.assertIsNone(controller.client)
                self.assertTrue(controller.connect());self.assertIs(controller.client,good)
