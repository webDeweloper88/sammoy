import json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).parent))
from board_runtime import compose,ready


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'board.json'

    def select(self,name):
        self.state.write_text(json.dumps({'schema':1,'board_id':name,'confirmed':True,'method':'manual','confirmed_at':'2026-10-27T00:00:00+00:00'}))

    def test_legacy_compose_order_is_unchanged(self):
        self.assertEqual(compose('dry-fog',self.state),['docker','compose','-f','docker-compose.yml','-f','docker-compose.nfc-relay.yml','-f','docker-compose.dry-fog.yml'])
        self.assertEqual(compose('full',self.state),['docker','compose','-f','docker-compose.yml'])

    def test_cl_never_adds_legacy_overlays(self):
        self.select('cl3566-a-e')
        for layout in ('full','nfc-relay','factory-only','dry-fog'):
            command=compose(layout,self.state)
            self.assertIn('docker-compose.cl3566.yml',command)
            self.assertNotIn('docker-compose.nfc-relay.yml',command)
            self.assertNotIn('docker-compose.dry-fog.yml',command)
        self.assertEqual(compose('factory-only',self.state)[-1],'docker-compose.factory.yml')
        with self.assertRaises(ValueError):compose('relay-only',self.state)

    def test_invalid_selection_never_defaults_to_legacy(self):
        self.state.write_text('{}')
        with self.assertRaises(ValueError):compose('full',self.state)

    def test_cubie_confirmed_preserves_compose(self):
        self.select('cubie-a7a')
        self.assertEqual(compose('nfc-relay',self.state)[-1],'docker-compose.nfc-relay.yml')
