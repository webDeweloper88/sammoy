import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import test_rebuild_application as old_tests

spec=importlib.util.spec_from_file_location('rebuild_v4',Path(__file__).parent/'windows/Rebuild-Application-V4.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

class RebuildV4Tests(unittest.TestCase):
    def fixture(self,base):
        root,app,factory,release=old_tests.ApplicationRevisionTests().fixture(base)
        source=base/'application'
        for unit in ('sammoy2-software-updates.service','sammoy2-update-cleanup.service','sammoy2-update-cleanup.timer'):(source/'deploy'/unit).write_text('[Unit]\nDescription=test\n')
        (source/'deploy/golden/sammoy2-factory-updates.service').write_text('[Unit]\nDescription=test\n')
        with tarfile.open(release/'application.tar.gz','w:gz') as tar:
            for p in source.iterdir():tar.add(p,arcname=p.name)
        deb=base/'test.deb';deb.write_bytes(b'deb')
        with tarfile.open(release/'update-deps.tar.gz','w:gz') as tar:tar.add(deb,arcname='test.deb')
        (release/'update-signing.pub.pem').write_text('public fixture')
        (release/'baseline-release.json').write_text('{}')
        return root,app,factory,release

    def test_offline_update_installs_units_but_no_clone_secret(self):
        with tempfile.TemporaryDirectory() as t:
            root,app,factory,release=self.fixture(Path(t))
            digest=v.builder.clean.sha(factory/'release.json')
            with patch.object(v,'PREVIOUS_RELEASE',digest):result=v.replace_release(root,release)
            self.assertTrue(result['software_updates']);self.assertTrue((factory/'update-debs/test.deb').exists())
            self.assertFalse((root/'etc/labrix-updates/agent.token').exists());self.assertFalse((root/'var/lib/labrix-updates/installed.json').exists())
            self.assertFalse((app/'.env').exists());self.assertEqual((app/'.hardware-profile').read_text(),'factory-only\n')
            self.assertIn('Requires=sammoy2-factory-updates.service',(root/'etc/systemd/system/sammoy2-post.service.d/factory-updates.conf').read_text())
            self.assertTrue((root/'etc/systemd/system/multi-user.target.wants/sammoy2-software-updates.service').is_symlink())
            self.assertEqual(json.loads((factory/'updates.json').read_text())['release_no'],2)

    def test_activated_image_is_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as t:
            root,app,factory,release=self.fixture(Path(t));(app/'.env').write_text('existing identity')
            with patch.object(v,'PREVIOUS_RELEASE',v.builder.clean.sha(factory/'release.json')),self.assertRaises(RuntimeError):v.replace_release(root,release)
            self.assertTrue((app/'original.txt').exists());self.assertFalse((root/'etc/labrix-updates').exists())
