import unittest
from app.device_profiles import profile,device_kind,catalog
from app.io_safety import validate_io
class DeviceProfilesTests(unittest.TestCase):
 def test_legacy_is_wash_and_bad_kind_is_rejected(self):
  self.assertEqual(device_kind(),'wash')
  with self.assertRaises(ValueError):profile('fog_typo')
 def test_fog_has_seven_services_and_separate_purge(self):
  p=profile('dry_fog');self.assertEqual(list(p['outputs'].values()),list(range(8)));self.assertEqual(len(p['client_programs']),7);self.assertNotIn('purge',p['client_programs']);self.assertEqual(p['outputs']['tank_air'],6);self.assertEqual(p['outputs']['purge'],7);self.assertFalse(p['requires_trigger']);self.assertFalse(p['live_activation_ready'])
 def test_defaults_are_per_second_and_no_automatic_cleaning_before_acceptance(self):
  d=profile('dry_fog')['defaults'];self.assertEqual(d['tariffs']['aroma_1']['amountSum'],1000);self.assertEqual(d['tariffs']['aroma_1']['durationSeconds'],1);self.assertEqual(d['paidPause']['amountSum'],250);self.assertEqual(d['paidPause']['durationSeconds'],1);self.assertEqual(d['freePauseSeconds'],300);self.assertFalse(d['purge']['enabled'])
 def test_wash_mapping_unchanged_and_catalog_cannot_be_mutated(self):
  self.assertEqual(profile()['outputs']['air'],7);p=profile('dry_fog');p['outputs']['purge']=0;self.assertEqual(profile('dry_fog')['outputs']['purge'],7);self.assertEqual(len(catalog()['profiles']),2)
 def test_wash_engine_rejects_fog_helper_before_start(self):
  with self.assertRaisesRegex(RuntimeError,'profile mismatch'):validate_io({'device_type':'dry_fog'})
