import importlib.util
import time
import unittest
from unittest.mock import Mock
spec=importlib.util.spec_from_file_location('network','deploy/admin-network-agent.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class NetworkTests(unittest.TestCase):
    def test_rejects_unsafe_addresses(self):
        for address,gateway in [('127.0.0.2','127.0.0.1'),('192.168.1.0','192.168.1.1'),('192.168.1.255','192.168.1.1'),('192.168.1.10','192.168.2.1'),('192.168.1.10','192.168.1.10')]:
            with self.subTest(address=address,gateway=gateway),self.assertRaises(ValueError):m.validate(dict(interface='eth0',mode='static',address=address,gateway=gateway,prefix=24))
    def test_only_physical_interfaces(self):
        with self.assertRaises(ValueError):m.validate({'interface':'docker0'})
    def test_new_profile_is_not_persistent_or_autoconnected(self):
        c=m.connection_settings(m.validate(dict(interface='eth0',mode='static',address='10.10.10.8',gateway='10.10.10.1',prefix=24)))
        self.assertFalse(c['connection']['autoconnect']);self.assertEqual(c['ipv4']['method'],'manual')
    def test_bad_wifi_password(self):
        with self.assertRaises(ValueError):m.validate(dict(interface='wlan0',ssid='test',password='short'))
    def test_apply_failure_rolls_back(self):
        n=m.Network.__new__(m.Network);n.nm=Mock();n.pending=Mock(return_value=None);n.props=Mock(return_value={});n.nm.GetDeviceByIpIface.return_value='/device';n.nm.CheckpointCreate.return_value='/checkpoint';n.nm.AddAndActivateConnection2.side_effect=RuntimeError('failure')
        with self.assertRaises(RuntimeError):n.apply({'interface':'eth0'})
        n.nm.CheckpointRollback.assert_called_once_with('/checkpoint')
    def test_cannot_confirm_disconnected_or_expiring_profile(self):
        n=m.Network.__new__(m.Network);n.check_pending=Mock(return_value={'expires_at':time.time()+60,'device':'/device','active':'/active'});n.props=Mock(return_value={'State':30});n.interface=Mock()
        with self.assertRaises(m.NetworkError):n.confirm({})
        n.interface.assert_not_called()
        n.check_pending.return_value['expires_at']=time.time()+5
        with self.assertRaises(m.NetworkError):n.confirm({})
