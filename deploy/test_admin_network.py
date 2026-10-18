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
    def test_isolated_lan_without_default_gateway(self):
        c=m.validate(dict(interface='eth0',mode='static',address='10.10.10.8',prefix=24,gateway=''))
        self.assertEqual(c['gateway'],'');self.assertEqual(c['dns'],[])
        self.assertEqual(m.connection_settings(c)['ipv4']['gateway'],'')
    def test_confirmation_persists_only_the_active_profile(self):
        from unittest.mock import patch
        n=m.Network.__new__(m.Network);n.nm=Mock();n.status=Mock(return_value={'ok':True})
        n.check_pending=Mock(return_value={'expires_at':time.time()+60,'device':'/device','active':'/active','connection':'/connection','checkpoint':'/checkpoint'})
        n.props=Mock(return_value={'State':100,'ActiveConnection':'/active'})
        connection=Mock();connection.GetSettings.return_value={'connection':{'autoconnect':False}}
        n.interface=Mock(return_value=connection)
        with patch.object(m,'STATE',Mock()):self.assertTrue(n.confirm({})['ok'])
        args=connection.Update2.call_args.args
        self.assertTrue(args[0]['connection']['autoconnect']);self.assertEqual(int(args[1]),1)
        n.nm.CheckpointDestroy.assert_called_once_with('/checkpoint')
    def test_explicit_rollback_and_stale_id(self):
        from unittest.mock import patch
        n=m.Network.__new__(m.Network);n.nm=Mock();n.nm.CheckpointRollback.return_value={'/device':0};n.status=Mock(return_value={'ok':True});n.pending=Mock(return_value={'id':'current','checkpoint':'/checkpoint'})
        with self.assertRaises(m.NetworkError):n.rollback({'id':'expired'})
        n.nm.CheckpointRollback.assert_not_called()
        with patch.object(m,'STATE',Mock()):self.assertTrue(n.rollback({'id':'current'})['ok'])
        n.nm.CheckpointRollback.assert_called_once_with('/checkpoint')

    def test_customer_subnets_are_not_bound_to_development_network(self):
        for address,prefix,gateway in [('192.168.50.20',23,'192.168.50.1'),('172.20.8.5',16,'172.20.0.1'),('10.42.0.10',24,'10.42.0.1')]:
            with self.subTest(address=address):
                value=m.validate(dict(interface='eth0',mode='static',address=address,prefix=prefix,gateway=gateway,dns=['9.9.9.9']))
                self.assertEqual(value['address'],address);self.assertEqual(value['prefix'],prefix)
                self.assertEqual(value['dns'],['9.9.9.9'])
