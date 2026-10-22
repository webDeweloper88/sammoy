import importlib.util,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('bill_config',Path(__file__).with_name('preserve-bill-config.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class PreserveBillConfigTests(unittest.TestCase):
 def test_enabled_default_in_active_profile_does_not_become_disabled(self):
  target={'bill_acceptor':{'enabled':False,'reader':'level'},'outputs':[{'name':'water','address':0}]}
  result=m.merge(target,{'gpio_line':33,'active_low':True})
  self.assertTrue(result['bill_acceptor']['enabled']);self.assertEqual(result['bill_acceptor']['reader'],'level')
  self.assertEqual(result['outputs'],target['outputs']);self.assertFalse(target['bill_acceptor']['enabled'])
 def test_explicit_disabled_and_reader_are_preserved(self):
  result=m.merge({'bill_acceptor':{'enabled':True,'reader':'edges'}},{'enabled':False,'reader':'level'})
  self.assertFalse(result['bill_acceptor']['enabled']);self.assertEqual(result['bill_acceptor']['reader'],'level')
 def test_invalid_configuration_refused(self):
  for current in (None,[],{'enabled':1}):
   with self.assertRaises(ValueError):m.merge({'bill_acceptor':{}},current)
