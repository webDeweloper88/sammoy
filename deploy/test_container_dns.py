import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('container_dns',Path(__file__).with_name('install-container-dns.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ContainerDnsTests(unittest.TestCase):
    def test_bridge_selects_ipv4_not_ipv6(self):
        self.assertEqual(m.bridge_address({'IPAM':{'Config':[{'Gateway':'fd00::1'},{'Gateway':'172.17.0.1'}]}}),'172.17.0.1')
    def test_missing_bridge_is_rejected(self):
        with self.assertRaises(RuntimeError):m.bridge_address({'IPAM':{'Config':[]}})
    def test_preserves_other_daemon_settings(self):
        previous={'log-driver':'json-file','live-restore':True}
        updated=m.daemon_configuration(previous,'172.17.0.1')
        self.assertEqual(updated,dict(previous,dns=['172.17.0.1']))
        self.assertNotIn('dns',previous)
        self.assertEqual(m.daemon_configuration(updated,'172.17.0.1'),updated)
    def test_does_not_replace_operator_dns(self):
        with self.assertRaises(RuntimeError):m.daemon_configuration({'dns':['10.0.0.1']},'172.17.0.1')
