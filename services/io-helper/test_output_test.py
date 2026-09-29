import unittest
from unittest.mock import Mock
from output_test import OutputTest

class OutputTests(unittest.TestCase):
    def controller(self):return Mock(read_outputs=Mock(return_value=[False]*8))
    def test_finite_pulse_and_readback(self):
        c=self.controller(); t=OutputTest();wait=Mock();refresh=Mock()
        self.assertFalse(t.run(c,'water',refresh,wait)['actual'])
        self.assertEqual([a.args for a in c.write_output.call_args_list],[('water',True),('water',False)])
        wait.assert_called_once_with(1.0);self.assertIsNone(t.active)
    def test_error_still_switches_off(self):
        c=self.controller();t=OutputTest()
        with self.assertRaises(RuntimeError):t.run(c,'water',Mock(),Mock(side_effect=RuntimeError('lost request')))
        c.write_output.assert_called_with('water',False);self.assertIsNone(t.active)
    def test_rejects_active_equipment(self):
        c=self.controller();c.read_outputs.return_value=[True]+[False]*7
        with self.assertRaises(ValueError):OutputTest().run(c,'water',Mock())
        c.write_output.assert_not_called()
    def test_concurrent_test_rejected(self):
        c=self.controller();t=OutputTest()
        def wait(_):
            with self.assertRaises(ValueError):t.run(c,'foam',Mock())
        t.run(c,'water',Mock(),wait)
    def test_off_failure_is_not_success(self):
        c=self.controller();c.write_output.side_effect=[True,RuntimeError('OFF failed')];t=OutputTest()
        with self.assertRaises(RuntimeError):t.run(c,'water',Mock(),Mock())
