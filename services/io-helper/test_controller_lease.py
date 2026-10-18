import unittest
from controller_lease import ControllerLease
class LeaseTests(unittest.TestCase):
    def test_boundary_and_diagnostic_does_not_renew(self):
        now=[0.];lease=ControllerLease(clock=lambda:now[0])
        self.assertFalse(lease.valid());lease.heartbeat();now[0]=1.99
        self.assertTrue(lease.snapshot()['controller_lease_valid']);now[0]=2
        self.assertFalse(lease.valid());self.assertFalse(lease.snapshot()['controller_lease_valid'])
    def test_trip_sequence_and_boot_identity(self):
        a=ControllerLease();b=ControllerLease();self.assertNotEqual(a.boot_id,b.boot_id)
        a.trip('watchdog');a.trip('watchdog');self.assertEqual(a.trip_seq,1)
        a.heartbeat();self.assertEqual(a.snapshot()['safety_reason'],'watchdog')
        a.rearm();a.trip('modbus_error');self.assertEqual(a.trip_seq,2)
    def test_invalid_timeout_rejected(self):
        for value in (0,499,60001):
            with self.assertRaises(ValueError):ControllerLease(value)
