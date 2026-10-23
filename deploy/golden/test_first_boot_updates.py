import base64
from datetime import datetime,timezone,timedelta
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch,Mock
import sys

spec=importlib.util.spec_from_file_location('factory_updates',Path(__file__).with_name('first-boot-updates.py'))
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class FactoryUpdaterTests(unittest.TestCase):
    def fixture(self,root):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from update_protocol import canonical
        app=root/'app';(app/'deploy').mkdir(parents=True);(app/'GOLDEN_TEMPLATE.json').write_text('{}')
        factory=root/'factory';(factory/'update-debs').mkdir(parents=True);(factory/'update-debs/test.deb').write_bytes(b'dependency')
        state=root/'state';state.mkdir();(state/'factory-pending').touch();(state/'images-ready').touch()
        key=Ed25519PrivateKey.generate();(factory/'update-signing.pub.pem').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        issue=datetime(2020,1,1,tzinfo=timezone.utc)
        m={'schema':1,'product':'labrix-wash','release_no':2,'version':'2026.10.23.2','hardware':'cubie-a7a','arch':'aarch64','channel':'stable','issued_at':issue.isoformat(),'expires_at':(issue+timedelta(days=90)).isoformat(),'notes':{'ru':'x','uz':'x','en':'x'},'artifact':{'url':'https://pay.labrix.uz/api/v1/software/artifacts/'+'a'*64,'sha256':'a'*64,'bytes':1,'unpacked_bytes':1,'image_bytes':1},'services':{'wash-engine':'sha256:'+'b'*64},'db_contract':'c'*64,'agent_protocol':1,'wallet_protocol':1,'runtime_contract':1}
        envelope={'manifest':m,'signature':base64.b64encode(key.sign(canonical(m))).decode()};(factory/'baseline-release.json').write_text(json.dumps(envelope))
        files={name:u.digest(factory/name) for name in ('update-debs/test.deb','baseline-release.json','update-signing.pub.pem')}
        (factory/'updates.json').write_text(json.dumps({'format':1,'version':m['version'],'release_no':2,'files':files}))
        (state/'image-configs.json').write_text(json.dumps({'sammoy2-wash-engine:latest':{'config':m['services']['wash-engine'],'native':'sha256:native'}}))
        return app,factory,state

    def boot(self,root):
        app,factory,state=self.fixture(root)
        original=Path.read_bytes
        def read(path):return b'radxa,cubie-a7a\0' if str(path)=='/proc/device-tree/compatible' else original(path)
        with patch.multiple(u,APP=app,FACTORY=factory,STATE=state,CONFIG=root/'config',STORE=root/'store'),patch.object(Path,'read_bytes',read),patch.object(u.os,'uname',return_value=Mock(machine='aarch64')),patch.object(u.subprocess,'run') as install,patch.object(u.subprocess,'check_output',return_value=json.dumps([{'Id':'sha256:native','Architecture':'arm64'}])),patch.object(u,'initialize_bill_filter'):
            u.initialize();first=(root/'config/agent.token').read_text();u.initialize()
            self.assertEqual(install.call_count,1)
            self.assertEqual((root/'config/agent.token').read_text(),first)
            self.assertEqual((root/'config/agent.token').stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads((root/'store/installed.json').read_text())['release_no'],2)
        return first

    def test_first_boot_is_offline_idempotent_and_secrets_are_unique(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            self.assertNotEqual(self.boot(a),self.boot(b))

    def test_corrupted_dependency_is_rejected_before_dpkg(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);app,factory,state=self.fixture(root);(factory/'update-debs/test.deb').write_bytes(b'changed')
            original=Path.read_bytes
            def read(path):return b'radxa,cubie-a7a\0' if str(path)=='/proc/device-tree/compatible' else original(path)
            with patch.multiple(u,APP=app,FACTORY=factory,STATE=state,CONFIG=root/'config',STORE=root/'store'),patch.object(Path,'read_bytes',read),patch.object(u.os,'uname',return_value=Mock(machine='aarch64')),patch.object(u.subprocess,'run') as install:
                with self.assertRaises(RuntimeError):u.initialize()
                install.assert_not_called();self.assertFalse((state/'updates-ready').exists())

    def test_bill_filter_creates_unique_zero_streams_and_never_resets_pulses(self):
        project=Path(__file__).resolve().parents[2];streams=[]
        with tempfile.TemporaryDirectory() as t:
            for name in ('a','b'):
                root=Path(t)/name;(root/'services/io-helper').mkdir(parents=True)
                for source in ('pulse_journal.py','bill_filter.py'):shutil.copyfile(project/'services/io-helper'/source,root/'services/io-helper'/source)
                with patch.object(u,'APP',root):
                    u.initialize_bill_filter();u.initialize_bill_filter()
                    from pulse_journal import PulseJournal
                    counter=PulseJournal(root/'data/io-helper/nv9.sqlite3');streams.append(counter.stream_id)
                    self.assertEqual(counter.get_setting('bill_filter')['min_gap_ms'],25)
                    counter.increment();counter.close()
                    with self.assertRaises(RuntimeError):u.initialize_bill_filter()
                    counter=PulseJournal(root/'data/io-helper/nv9.sqlite3');self.assertEqual(counter.value(),1);counter.close()
            self.assertNotEqual(*streams)
