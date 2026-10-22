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

class TemporaryInternetTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        for name in ('TEMP','STATE'):
            handle=patch.object(m,name,Path(self.directory.name)/name);handle.start();self.addCleanup(handle.stop)
    def network(self):
        n=m.Network.__new__(m.Network);n.nm=Mock();n.pending=Mock(return_value=None);n.status=Mock(return_value={'ok':True});return n
    def test_temporary_profile_priority_without_autoconnect(self):
        c=m.connection_settings(m.validate(dict(interface='wlan0',temporary=True,ssid='Phone',password='test-pass')))
        self.assertFalse(c['connection']['autoconnect'])
        self.assertEqual(c['connection']['id'],'LABRIX temporary setup internet')
        for version in ('ipv4','ipv6'):
            self.assertEqual(c[version]['route-metric'],5);self.assertLess(c[version]['dns-priority'],0)
        with self.assertRaises(ValueError):m.validate(dict(interface='eth0',temporary=True))
    def test_connect_uses_memory_wifi_checkpoint_and_excludes_secrets_from_state(self):
        n=self.network();n.props=Mock(side_effect=[{}, {'ActiveConnection':'/old-active'}, {'Connection':'/old-connection'}]);n.nm.GetDeviceByIpIface.return_value='/wifi';n.nm.CheckpointCreate.return_value='/checkpoint';n.nm.AddAndActivateConnection2.return_value=('/connection','/active',{})
        n.temporary_connect({'ssid':'Phone','password':'test-pass','interface':'eth0'})
        n.nm.GetDeviceByIpIface.assert_called_once_with('wlan0')
        self.assertEqual(list(n.nm.CheckpointCreate.call_args.args[0]),['/wifi'])
        self.assertEqual(n.nm.AddAndActivateConnection2.call_args.args[3]['persist'],'memory')
        data=m.json.loads(m.STATE.read_text());self.assertEqual(data['previous_connection'],'/old-connection');self.assertNotIn('test-pass',m.STATE.read_text())
    def test_confirm_never_persists_or_reads_secrets(self):
        n=self.network();pending=dict(id='test',expires_at=time.time()+80,device='/wifi',active='/active',connection='/connection',checkpoint='/checkpoint',temporary=True,previous_connection='/old',ssid='Phone')
        n.check_pending=Mock(return_value=pending);n.props=Mock(return_value={'State':100,'ActiveConnection':'/active'});n.interface=Mock();n.status.return_value={'ok':True,'temporary_subnet_conflict':False,'interfaces':[{'interface':'wlan0','address':'192.168.43.2','gateway':'192.168.43.1'}]}
        n.confirm({'id':'test'})
        n.interface.return_value.GetSecrets.assert_not_called();n.interface.return_value.Update2.assert_not_called()
        self.assertLess(abs(m.read_temporary()['expires_at']-time.time()-7200),2)
        self.assertEqual(m.TEMP.stat().st_mode&0o777,0o600)
    def test_overlapping_subnets_are_rolled_back(self):
        self.assertTrue(m.overlapping_networks([{'interface':'eth0','connected':True,'address':'192.168.42.2','prefix':23},{'interface':'wlan0','connected':True,'address':'192.168.43.3','prefix':24}]))
        n=self.network();n.check_pending=Mock(return_value=dict(id='test',expires_at=time.time()+80,device='/wifi',active='/active',connection='/connection',temporary=True));n.props=Mock(return_value={'State':100,'ActiveConnection':'/active'});n.interface=Mock();n.status.return_value={'temporary_subnet_conflict':True};n.rollback=Mock()
        with self.assertRaises(m.NetworkError):n.confirm({'id':'test'})
        n.rollback.assert_called_once_with({'id':'test'});self.assertFalse(m.TEMP.exists())
    def test_disconnect_deletes_only_temp_and_restores_previous_wifi(self):
        n=self.network();n.props=Mock(return_value={'ActiveConnection':'/active'});n.interface=Mock();n.interface.return_value.GetSettings.return_value={'connection':{'id':'LABRIX temporary setup internet'}}
        m.save_temporary(dict(active='/active',device='/wifi',connection='/connection',previous_connection='/old',expires_at=time.time()+100))
        n.temporary_disconnect({})
        n.nm.DeactivateConnection.assert_called_once_with('/active');n.interface.return_value.Delete.assert_called_once();n.nm.ActivateConnection.assert_called_once_with('/old','/wifi',m.dbus.ObjectPath('/'));self.assertFalse(m.TEMP.exists())
    def test_finish_delays_cleanup_for_browser_response(self):
        n=self.network();m.save_temporary(dict(expires_at=time.time()+7200,ssid='Phone'))
        result=n.temporary_finish({});self.assertTrue(result['scheduled']);self.assertLess(abs(result['disconnect_at']-time.time()-30),2)
        n.nm.DeactivateConnection.assert_not_called()
    def test_failed_restore_does_not_leave_stale_temp_state(self):
        n=self.network();n.props=Mock(return_value={'ActiveConnection':'/active'});n.interface=Mock();n.interface.return_value.GetSettings.return_value={'connection':{'id':'LABRIX temporary setup internet'}};n.nm.ActivateConnection.side_effect=m.dbus.DBusException('unavailable')
        m.save_temporary(dict(active='/active',device='/wifi',connection='/connection',previous_connection='/old'))
        self.assertIn('warning',n.temporary_disconnect({}));self.assertFalse(m.TEMP.exists())
