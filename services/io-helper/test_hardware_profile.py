import unittest
from copy import deepcopy
from hardware_profile import validate_profile,FOG_OUTPUTS
class HardwareProfileTests(unittest.TestCase):
 def config(self):return {'device_type':'dry_fog','outputs':[{'name':n,'address':a} for n,a in FOG_OUTPUTS.items()],'safety':{'startup_all_off':True}}
 def test_legacy_and_dry_fog_profile(self):
  self.assertEqual(validate_profile({}),'wash');self.assertEqual(validate_profile(self.config()),'dry_fog')
 def test_wrong_mapping_and_duplicate_addresses_fail(self):
  for rows in [[{'name':'air','address':7}],self.config()['outputs']+[{ 'name':'purge','address':7}]]:
   c=self.config();c['outputs']=rows
   with self.assertRaises(ValueError):validate_profile(c)
  c=self.config();c['outputs'][0]['address']=True
  with self.assertRaises(ValueError):validate_profile(c)
 def test_unknown_type_and_missing_shutdown_fail(self):
  with self.assertRaises(ValueError):validate_profile({'device_type':'unknown'})
  c=self.config();c['safety']={}
  with self.assertRaises(ValueError):validate_profile(c)
