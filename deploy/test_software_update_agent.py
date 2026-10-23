import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch,Mock
from uuid import uuid4
spec=importlib.util.spec_from_file_location('software_agent',Path(__file__).with_name('software-update-agent.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class AgentTests(unittest.TestCase):
    def package(self,folder,name,content):
        archive=folder/'test.tar.gz'
        with tarfile.open(archive,'w:gz') as t:
            info=tarfile.TarInfo(name);info.size=len(content);t.addfile(info,io.BytesIO(content))
        return archive
    def test_path_traversal_archive_never_writes_outside_job(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);archive=self.package(folder,'../../evil',b'bad')
            with self.assertRaises(a.UpdateError):a.unpack(archive,folder,{'artifact':{'unpacked_bytes':3}})
            self.assertFalse((folder.parent/'evil').exists())
    def test_mutable_docker_tags_are_rejected_before_load(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);inner=io.BytesIO()
            with tarfile.open(fileobj=inner,mode='w') as tar:
                content=json.dumps([{'Config':'a'*64+'.json','RepoTags':['sammoy2-wash-engine:latest']}]).encode();info=tarfile.TarInfo('manifest.json');info.size=len(content);tar.addfile(info,io.BytesIO(content))
            data=inner.getvalue();archive=self.package(folder,'images.tar',data)
            with self.assertRaisesRegex(a.UpdateError,'mutable_tags'):a.unpack(archive,folder,{'artifact':{'unpacked_bytes':len(data)},'services':{'wash-engine':'sha256:'+'a'*64}})
    def test_insufficient_space_refuses_before_download_or_service_stop(self):
        with tempfile.TemporaryDirectory() as t,patch.object(a,'STORE',Path(t)),patch.object(a,'verify',return_value={'artifact':{'bytes':10,'unpacked_bytes':20,'image_bytes':30}}),patch.object(a,'compose',return_value=['docker','compose']),patch.object(a,'cleanup'),patch.object(a,'db_info',return_value=('test','db',40)),patch.object(a.shutil,'disk_usage',return_value=Mock(free=1)),patch.object(a,'download') as download,patch.object(a,'run') as run:
            job={'id':str(uuid4()),'envelope':{}};a.perform(job)
            self.assertEqual(job['status'],'failed');self.assertEqual(job['error'],'insufficient_space');download.assert_not_called();run.assert_not_called()
    def test_invalid_signature_fails_before_docker_or_download(self):
        with tempfile.TemporaryDirectory() as t,patch.object(a,'STORE',Path(t)),patch.object(a,'verify',side_effect=a.UpdateError('invalid_release_signature')),patch.object(a,'run') as run,patch.object(a,'download') as download:
            job={'id':str(uuid4()),'envelope':{},'status':'queued'};a.perform(job)
            self.assertEqual(job['status'],'failed');run.assert_not_called();download.assert_not_called()
    def test_submission_idempotence_never_starts_second_worker(self):
        with tempfile.TemporaryDirectory() as t,patch.object(a,'STORE',Path(t)),patch.object(a,'verify'),patch.object(a,'idle'),patch.object(a.threading,'Thread') as worker:
            value={'id':str(uuid4()),'envelope':{'manifest':{}}}
            first=a.submit(value);second=a.submit(value)
            self.assertEqual(first,second);self.assertEqual(worker.call_count,1)
            with self.assertRaises(a.UpdateError):a.submit({'id':value['id'],'envelope':{'changed':True}})
    def test_health_failure_rolls_back_images_without_restoring_money(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);store=folder/'store';job_id=str(uuid4());work=store/'jobs'/job_id;work.mkdir(parents=True)
            archive=work/'package.tar.gz';archive.write_bytes(b'x')
            images=work/'images.tar';images.write_bytes(b'x')
            m={'services':{'wash-engine':'sha256:new'},'db_contract':'schema'}
            commands=[]
            def run(*args,**kw):
                commands.append(args)
                if args[:2]==('docker','inspect'):return json.dumps([{'Image':'sha256:old','Config':{'Image':'sammoy2-wash-engine:latest'}}]).encode()
                if args[:3]==('docker','image','inspect'):return json.dumps([{'Id':'sha256:new','Architecture':'arm64','Os':'linux'}]).encode()
                return b''
            baseline={'stream':'kept','pulses':123}
            with patch.object(a,'STORE',store),patch.object(a,'verify',return_value=m),patch.object(a,'compose',return_value=['docker','compose']),patch.object(a,'cleanup'),patch.object(a,'db_info',return_value=('user','db',1)),patch.object(a,'space_required',return_value=1),patch.object(a,'download',return_value=archive),patch.object(a,'unpack',return_value=images),patch.object(a,'config_references',return_value={'sha256:new':'sha256:new'}),patch.object(a,'schema_contract',return_value='schema'),patch.object(a,'idle',return_value=baseline),patch.object(a,'journal',return_value=baseline),patch.object(a,'maintenance'),patch.object(a,'backup') as backup,patch.object(a,'run',side_effect=run),patch.object(a,'health',side_effect=[a.UpdateError('health_check_failed'),None]):
                job={'id':job_id,'envelope':{}};a.perform(job)
            self.assertEqual(job['status'],'rolled_back');backup.assert_called_once()
            self.assertIn(('docker','tag','sha256:old','sammoy2-wash-engine:latest'),commands)
            self.assertFalse((store/'installed.json').exists())

    def test_cleanup_preserves_unmanaged_data_and_unreviewed_backup(self):
        with tempfile.TemporaryDirectory() as t,patch.object(a,'STORE',Path(t)),patch.object(a,'run'):
            root=Path(t);old=root/'jobs'/'old';old.mkdir(parents=True)
            a.atomic(old/'job.json',{'status':'completed','finished_at':1,'rollback_tags':{}})
            (old/'database.dump').write_bytes(b'backup');(root/'unmanaged').write_bytes(b'keep')
            failed=root/'jobs'/'failed';failed.mkdir();a.atomic(failed/'job.json',{'status':'needs_review','finished_at':1});(failed/'database.dump').write_bytes(b'keep')
            a.cleanup(now=a.RETAIN+2)
            self.assertFalse((old/'database.dump').exists());self.assertTrue((failed/'database.dump').exists());self.assertTrue((root/'unmanaged').exists())
