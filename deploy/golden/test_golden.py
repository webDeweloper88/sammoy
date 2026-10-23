import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from identity import initialize
from template import export

class GoldenTests(unittest.TestCase):
    def fixture(self, root):
        (root/'docker-compose.yml').write_text('services: {}')
        (root/'config').mkdir(); (root/'config/io-map.yaml').write_text('outputs: {}')
        (root/'.env').write_text('SECRET=live')
        (root/'data').mkdir(); (root/'data/money').write_text('customer ledger')
        (root/'tokenGit').write_text('secret')
    def test_export_has_no_live_secrets_or_money(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source'; root.mkdir(); self.fixture(root)
            dst=export(Path(tmp)/'template',root)
            self.assertFalse((dst/'.env').exists()); self.assertFalse((dst/'data').exists())
            self.assertFalse((dst/'tokenGit').exists()); self.assertTrue((dst/'config/io-map.yaml').exists())
            self.assertEqual((root/'data/money').read_text(),'customer ledger')
    def test_each_clone_gets_unique_secrets_and_no_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            clones=[]
            for n in ('a','b'):
                root=Path(tmp)/n; root.mkdir(); (root/'GOLDEN_TEMPLATE.json').write_text('{}')
                initialize(root); clones.append(root)
                before=(root/'.env').read_bytes()
                with self.assertRaises(RuntimeError): initialize(root)
                self.assertEqual(before,(root/'.env').read_bytes())
                self.assertEqual((root/'.env').stat().st_mode & 0o777,0o600)
            self.assertNotEqual((clones[0]/'.env').read_bytes(),(clones[1]/'.env').read_bytes())
            values=[]
            for root in clones:
                env=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines())
                self.assertEqual(env['IO_BILL_LEVEL_PROCESS'],'1')
                self.assertEqual(env['IO_BILL_SAMPLER_NICE'],'-10')
                self.assertEqual(env['WASH_ENGINE_DEFAULT_OWNER_PASSWORD'],'labrix')
                self.assertEqual(env['WASH_ENGINE_DEFAULT_ADMIN_PASSWORD'],'labrix')
                handover=json.loads((root/'factory-access.json').read_text())
                self.assertTrue(handover['must_change_password'])
                self.assertEqual(handover['owner'],'labrix')
                self.assertEqual(handover['admin'],'labrix')
                values.append(env)
            for key in ('POSTGRES_PASSWORD','WASH_ENGINE_JWT_SECRET','TELEGRAM_SETUP_KEY','REPORT_API_KEY'):
                self.assertNotEqual(values[0][key],values[1][key])
    def test_live_data_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'GOLDEN_TEMPLATE.json').write_text('{}')
            (root/'data').mkdir(); (root/'data/money').write_text('keep')
            with self.assertRaises(RuntimeError): initialize(root)
            self.assertFalse((root/'.env').exists())
    def test_symlink_export_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source'; root.mkdir(); self.fixture(root)
            (root/'config/leak').symlink_to(root/'.env')
            dst=Path(tmp)/'template'
            with self.assertRaises(ValueError): export(dst,root)
            self.assertFalse(dst.exists())

if __name__=='__main__': unittest.main()
