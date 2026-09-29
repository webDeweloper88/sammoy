import unittest

from app.commissioning_access import commissioning_access_allowed


class CommissioningAccessTests(unittest.TestCase):
    def test_private_lan_is_allowed_only_before_commissioning(self):
        self.assertTrue(commissioning_access_allowed("10.10.10.25", complete=False))
        self.assertTrue(commissioning_access_allowed("172.20.1.8", complete=False))
        self.assertTrue(commissioning_access_allowed("192.168.1.12", complete=False))
        self.assertFalse(commissioning_access_allowed("10.10.10.25", complete=True))

    def test_loopback_remains_available_after_commissioning(self):
        self.assertTrue(commissioning_access_allowed("127.0.0.1", complete=True))
        self.assertTrue(commissioning_access_allowed("::1", complete=True))

    def test_public_or_invalid_address_is_never_allowed(self):
        self.assertFalse(commissioning_access_allowed("8.8.8.8", complete=False))
        self.assertFalse(commissioning_access_allowed("not-an-ip", complete=False))


if __name__ == "__main__":
    unittest.main()
