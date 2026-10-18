import unittest
from input_filter import InputFilter
class InputFilterTests(unittest.TestCase):
    def test_activation_requires_continuous_contact(self):
        f=InputFilter(40)
        self.assertFalse(f.observe(True,0));self.assertFalse(f.observe(True,.039));self.assertTrue(f.observe(True,.04))
    def test_release_is_immediate_and_bounce_restarts_confirmation(self):
        f=InputFilter(40);f.observe(True,0);self.assertFalse(f.observe(False,.03));self.assertFalse(f.observe(True,.04));self.assertFalse(f.observe(True,.079));self.assertTrue(f.observe(True,.08));self.assertFalse(f.observe(False,.081))
    def test_zero_delay_retains_other_inputs(self):
        f=InputFilter();self.assertTrue(f.observe(True,0));self.assertFalse(f.observe(False,.001))
    def test_disconnect_discards_previous_state(self):
        f=InputFilter(40);f.observe(True,0);f.observe(True,.05);f.reset();self.assertFalse(f.observe(True,10));self.assertTrue(f.observe(True,10.04))
    def test_invalid_configuration_rejected(self):
        for value in [-1,True,'40',float('nan'),5001]:
            with self.subTest(value=value),self.assertRaises(ValueError):InputFilter(value)
