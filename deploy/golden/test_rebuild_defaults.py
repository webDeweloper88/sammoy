import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('defaults_revision',Path(__file__).parent/'windows/Rebuild-Defaults.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)


class DefaultRevisionTests(unittest.TestCase):
    def fixture(self,root):
        (root/'var/lib/sammoy2').mkdir(parents=True)
        (root/'var/lib/sammoy2/factory-pending').touch()
        app=root/'opt/sammoy/sammoy2';(app/'deploy/golden').mkdir(parents=True)
        (app/'GOLDEN_TEMPLATE.json').write_text('{}')
        target=app/'deploy/golden/identity.py';target.write_bytes(b'# original factory\n')
        return app,target

    def test_only_uninitialized_identity_script_is_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);app,target=self.fixture(root)
            replacement=(Path(__file__).parent/'identity.py').read_bytes()
            with patch.object(helper,'PREVIOUS_IDENTITY',hashlib.sha256(target.read_bytes()).hexdigest()):
                helper.replace_identity(root,replacement)
            self.assertEqual(target.read_bytes(),replacement)
            self.assertFalse((app/'.env').exists())
            self.assertTrue((root/'var/lib/sammoy2/factory-pending').exists())

    def test_initialized_image_or_database_refuses_any_changes(self):
        for name in ('.env','.factory-identity-ready','factory-access.json','data/postgres/PG_VERSION'):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);app,target=self.fixture(root);before=target.read_bytes()
                p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('existing identity')
                with self.assertRaises(RuntimeError):helper.replace_identity(root,b'anything')
                self.assertEqual(target.read_bytes(),before)
                self.assertEqual(p.read_text(),'existing identity')

    def test_unexpected_factory_script_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);app,target=self.fixture(root);before=target.read_bytes()
            with self.assertRaises(RuntimeError):helper.replace_identity(root,b'anything')
            self.assertEqual(target.read_bytes(),before)
