import unittest
from pathlib import Path
import yaml

class WashInputMapTests(unittest.TestCase):
    def test_all_wash_maps_use_same_eight_input_contract_and_keep_outputs(self):
        root=Path('/repo/config')
        if not root.exists():self.skipTest('Repository config mount required')
        expected=['pause_button','total_stop','mode_water','mode_osmos','mode_nano','mode_foam','mode_wax','mode_chem']
        for filename in ('io-map.yaml','io-map.nfc-relay.yaml','io-map.relay-only.yaml','io-map.cl3566.yaml'):
            cfg=yaml.safe_load((root/filename).read_text())
            self.assertEqual([x['name'] for x in cfg['inputs']],expected,filename)
            self.assertEqual([x['address'] for x in cfg['inputs']],list(range(8)))
            self.assertFalse(cfg['inputs'][1]['active_low'])
            self.assertTrue(all(not x['active_low'] for x in cfg['inputs']))
            self.assertEqual([x['name'] for x in cfg['outputs']],['water','osmos','nano','foam','wax','chem','vacuum','air'])
