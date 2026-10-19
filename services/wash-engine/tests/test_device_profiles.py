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


class DryFogReadbackTests(unittest.TestCase):
    def io(self):
        return {'device_type':'dry_fog','inputs':{},'outputs':dict.fromkeys(profile('dry_fog')['outputs'],False),'modbus_ok':True,'poll_age_seconds':0,'nv9_enabled':False}

    def test_each_output_requires_matching_confirmation(self):
        from app.io_safety import validate_io
        for output in profile('dry_fog')['outputs']:
            io=self.io();io['outputs'][output]=True
            validate_io(io,output,'dry_fog')
            with self.assertRaises(RuntimeError):validate_io(io,None,'dry_fog')
            io['outputs']['aroma_2' if output!='aroma_2' else 'purge']=True
            with self.assertRaises(RuntimeError):validate_io(io,output,'dry_fog')

    def test_legacy_or_wrong_map_cannot_prove_fog_outputs_off(self):
        from app.io_safety import validate_io
        for change in ({'inputs':[]},{'outputs':dict.fromkeys(profile('wash')['outputs'],False)},{'outputs':{**self.io()['outputs'],'unknown':True}},{'poll_age_seconds':2}):
            with self.assertRaises(RuntimeError):validate_io({**self.io(),**change},None,'dry_fog')
        validate_io(self.io(),None,'dry_fog')
