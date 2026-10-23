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

class UpdateFailureScenarios(unittest.TestCase):
    def scenario(self, *, idle_effect=None, journal=None, backup_error=False, health_effect=None):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as t, ExitStack() as stack:
            root=Path(t);job_id=str(uuid4());folder=root/'jobs'/job_id;folder.mkdir(parents=True)
            archive=folder/'package.tar.gz';archive.write_bytes(b'archive')
            images=folder/'images.tar';images.write_bytes(b'images')
            old={'release_no':2,'version':'previous'};a.atomic(root/'installed.json',old)
            baseline={'stream':'unchanged','pulses':500};commands=[]
            def command(*args,**kwargs):
                commands.append(args)
                if args[:2]==('docker','inspect'):return json.dumps([{'Image':'sha256:old','Config':{'Image':'sammoy2-wash-engine:latest'}}]).encode()
                if args[:3]==('docker','image','inspect'):return json.dumps([{'Id':'sha256:new','Architecture':'arm64','Os':'linux'}]).encode()
                return b''
            overrides={'STORE':root,'verify':Mock(return_value={'services':{'wash-engine':'sha256:new'},'db_contract':'unchanged'}),'compose':Mock(return_value=['docker','compose']), 'cleanup':Mock(),'db_info':Mock(return_value=('user','db',1)),'space_required':Mock(return_value=1),'download':Mock(return_value=archive),'unpack':Mock(return_value=images),'config_references':Mock(return_value={'sha256:new':'sha256:new'}),'schema_contract':Mock(return_value='unchanged'),'idle':Mock(side_effect=idle_effect) if idle_effect else Mock(return_value=baseline),'journal':Mock(return_value=journal or baseline),'maintenance':Mock(),'backup':Mock(side_effect=a.UpdateError('database_backup_failed') if backup_error else None),'run':Mock(side_effect=command),'health':Mock(side_effect=health_effect)}
            for name,value in overrides.items():stack.enter_context(patch.object(a,name,value))
            job={'id':job_id,'envelope':{}};a.perform(job)
            installed=a.load(root/'installed.json')
            self.assertFalse(archive.exists());self.assertFalse(images.exists())
            self.assertFalse(any('pg_restore' in str(c) for c in commands),'Rollback must never restore an old monetary database')
            return job,commands,installed,overrides

    def test_session_appearing_during_download_prevents_service_stop(self):
        job,commands,installed,m=self.scenario(idle_effect=[a.UpdateError('station_busy')])
        self.assertEqual(job['status'],'failed');self.assertEqual(installed['release_no'],2)
        self.assertFalse(any('stop' in c for c in commands));m['backup'].assert_not_called()

    def test_pulse_arriving_before_stop_cancels_and_restores_services(self):
        job,commands,installed,m=self.scenario(journal={'stream':'unchanged','pulses':501})
        self.assertEqual(job['status'],'rolled_back');self.assertEqual(job['error'],'cash_changed_before_install')
        m['backup'].assert_not_called();self.assertEqual(installed['release_no'],2)
        self.assertNotIn(('docker','tag','sha256:new','sammoy2-wash-engine:latest'),commands)

    def test_backup_failure_never_activates_candidate(self):
        job,commands,installed,m=self.scenario(backup_error=True)
        self.assertEqual(job['status'],'rolled_back');self.assertEqual(job['error'],'database_backup_failed')
        self.assertNotIn(('docker','tag','sha256:new','sammoy2-wash-engine:latest'),commands)
        self.assertEqual(installed['release_no'],2)

    def test_failed_candidate_returns_previous_release_and_preserves_receipt(self):
        job,commands,installed,m=self.scenario(health_effect=[a.UpdateError('health_check_failed'),None])
        self.assertEqual(job['status'],'rolled_back');self.assertEqual(installed,{'release_no':2,'version':'previous'})
        self.assertIn(('docker','tag','sha256:old','sammoy2-wash-engine:latest'),commands)
        self.assertEqual(m['health'].call_count,2)

    def test_new_customer_session_prevents_rollback_restart(self):
        baseline={'stream':'unchanged','pulses':500}
        job,commands,installed,m=self.scenario(idle_effect=[baseline,a.UpdateError('station_busy')],health_effect=[a.UpdateError('health_check_failed')])
        self.assertEqual(job['status'],'needs_review');self.assertEqual(installed['release_no'],2)
        self.assertNotIn(('docker','tag','sha256:old','sammoy2-wash-engine:latest'),commands)
        self.assertEqual(sum('up' in c for c in commands),1)

    def test_failed_rollback_is_not_reported_as_success(self):
        job,commands,installed,m=self.scenario(health_effect=[a.UpdateError('health_check_failed'),a.UpdateError('health_check_failed')])
        self.assertEqual(job['status'],'needs_review');self.assertEqual(installed['release_no'],2)

    def test_idle_checks_each_money_and_output_guard(self):
        for field in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld','vipRemainingSeconds'):
            with self.subTest(field=field),patch.object(a,'get',return_value={'state':{'outputsOffConfirmed':True,field:1}}):
                with self.assertRaisesRegex(a.UpdateError,'station_busy'):a.idle()
        with patch.object(a,'get',return_value={'state':{'outputsOffConfirmed':False}}):
            with self.assertRaisesRegex(a.UpdateError,'outputs_not_confirmed_off'):a.idle()

    def test_input_fault_and_active_bill_block_install(self):
        for state in ({'active':True},{'fault':'stuck'}):
            with self.subTest(state=state),patch.object(a,'get',side_effect=[{'state':{'outputsOffConfirmed':True}},state]):
                with self.assertRaisesRegex(a.UpdateError,'cash_input_not_ready'):a.idle()

class SubmissionSafetyTests(unittest.TestCase):
    def test_second_different_job_is_rejected_while_first_is_running(self):
        with tempfile.TemporaryDirectory() as t,patch.object(a,'STORE',Path(t)),patch.object(a,'verify'),patch.object(a,'idle'),patch.object(a.threading,'Thread') as worker:
            a.submit({'id':str(uuid4()),'envelope':{'manifest':{}}})
            with self.assertRaisesRegex(a.UpdateError,'another_update_pending'):
                a.submit({'id':str(uuid4()),'envelope':{'manifest':{}}})
            self.assertEqual(worker.call_count,1)

    def test_old_release_cannot_be_installed_as_a_new_update(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);public=folder/'public';public.write_bytes(b'fixture');hardware=folder/'hardware';hardware.write_text('cubie-a7a');a.atomic(folder/'installed.json',{'release_no':2})
            with patch.object(a,'STORE',folder),patch.object(a,'PUBLIC',public),patch.object(a,'HARDWARE',hardware),patch.object(a.os,'uname',return_value=Mock(machine='aarch64')),patch.object(a,'verify_release',return_value={'hardware':'cubie-a7a','arch':'aarch64','release_no':1}):
                with self.assertRaisesRegex(a.UpdateError,'release_not_newer'):a.verify({})
