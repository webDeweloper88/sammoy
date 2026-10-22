import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('application_revision',Path(__file__).parent/'windows/Rebuild-Application.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)


class ApplicationRevisionTests(unittest.TestCase):
    def fixture(self,base):
        root=base/'offline';app=root/'opt/sammoy/sammoy2'
        (app/'deploy/golden').mkdir(parents=True)
        (app/'GOLDEN_TEMPLATE.json').write_text('{}')
        (app/'.hardware-profile').write_text('factory-only\n')
        (app/'original.txt').write_text('old source')
        (root/'var/lib/sammoy2').mkdir(parents=True)
        (root/'var/lib/sammoy2/factory-pending').touch()
        factory=root/'opt/labrix-factory';factory.mkdir()
        (factory/'release.json').write_text('old release')
        (factory/'images.json').write_text('old manifest')
        (factory/'images.tar.gz').write_text('old archive')
        release=base/'release';release.mkdir()
        source=base/'application';(source/'deploy/golden').mkdir(parents=True)
        (source/'services/wash-engine/app').mkdir(parents=True)
        (source/'GOLDEN_TEMPLATE.json').write_text('{}')
        (source/'deploy/golden/identity.py').write_text("DEFAULT_OWNER_PASSWORD = 'labrix'\nDEFAULT_ADMIN_PASSWORD = 'labrix'\n")
        (source/'services/wash-engine/app/wallet_management.py').write_text("# management-probe\n")
        with tarfile.open(release/'application.tar.gz','w:gz') as t:
            for p in source.iterdir():t.add(p,arcname=p.name)
        for name in ('images.tar.gz','images.json','release.json'):(release/name).write_text('new '+name)
        return root,app,factory,release

    def test_replaces_only_factory_application_and_keeps_os_and_markers(self):
        with tempfile.TemporaryDirectory() as d:
            root,app,factory,release=self.fixture(Path(d))
            (root/'etc').mkdir();(root/'etc/fstab').write_text('unchanged')
            digest=helper.builder.clean.sha(factory/'release.json')
            with patch.object(helper,'PREVIOUS_RELEASE',digest):helper.replace_release(root,release)
            self.assertEqual((root/'etc/fstab').read_text(),'unchanged')
            self.assertTrue((root/'var/lib/sammoy2/factory-pending').exists())
            self.assertFalse((app/'original.txt').exists())
            self.assertFalse((app/'.env').exists())
            self.assertEqual((app/'.hardware-profile').read_text(),'factory-only\n')
            self.assertEqual((factory/'images.tar.gz').read_bytes(),(release/'images.tar.gz').read_bytes())

    def test_rejects_booted_identity_data_and_applied_hardware_without_writing(self):
        paths=['opt/sammoy/sammoy2/.env','opt/sammoy/sammoy2/factory-access.json',
               'opt/sammoy/sammoy2/.factory-identity-ready','opt/sammoy/sammoy2/data/postgres/PG_VERSION',
               'var/lib/sammoy2/os-identity-ready','var/lib/sammoy2/images-ready',
               'opt/sammoy/sammoy2/.hardware-profile']
        for relative in paths:
            with self.subTest(path=relative),tempfile.TemporaryDirectory() as d:
                root,app,factory,release=self.fixture(Path(d));p=root/relative
                p.parent.mkdir(parents=True,exist_ok=True);p.write_text('existing state')
                digest=helper.builder.clean.sha(factory/'release.json')
                with patch.object(helper,'PREVIOUS_RELEASE',digest),self.assertRaises(RuntimeError):helper.replace_release(root,release)
                self.assertEqual((app/'original.txt').read_text(),'old source')
                self.assertEqual((factory/'images.tar.gz').read_text(),'old archive')

    def test_symlink_data_cannot_escape_offline_root(self):
        with tempfile.TemporaryDirectory() as d:
            root,app,factory,release=self.fixture(Path(d));outside=Path(d)/'outside';outside.mkdir()
            (app/'data').symlink_to(outside,target_is_directory=True)
            digest=helper.builder.clean.sha(factory/'release.json')
            with patch.object(helper,'PREVIOUS_RELEASE',digest),self.assertRaises(RuntimeError):helper.replace_release(root,release)
            self.assertEqual(list(outside.iterdir()),[])

    def test_release_checksum_rejects_modified_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            names=['application.tar.gz','images.tar.gz','images.json','installer.pub']
            for name in names:(root/name).write_text(name)
            manifest={'state':'CLEAN_ARM64_APPLICATION_RELEASE','files':{n:helper.builder.clean.sha(root/n) for n in names}}
            (root/'release.json').write_text(json.dumps(manifest))
            with patch.object(helper,'EXPECTED_RELEASE',helper.builder.clean.sha(root/'release.json')):
                helper.verify_release(root)
                (root/'images.tar.gz').write_text('corrupt')
                with self.assertRaises(RuntimeError):helper.verify_release(root)
