"""No real host commands: exercise ordering and failure fences with mocks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import os
import subprocess
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('system_agent',Path(__file__).with_name('admin-system-agent.py'))
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)


class SystemAgentTests(unittest.TestCase):
    def test_profile_off_proof_failure_restores_backend_without_starting_profile(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bin_dir=root/'bin';bin_dir.mkdir();log=root/'commands'
            (root/'.hardware-profile').write_text('factory-only\n')
            programs={
                'id':'#!/bin/sh\necho 0\n',
                'python3':'#!/bin/sh\ncat >/dev/null\n[ "$#" != 1 ] || echo wash\nexit 0\n',
                'docker':'#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_LOG"\ncase "$*" in "exec sammoy2-io-helper"*) exit 1;; esac\nexit 0\n'}
            for name,body in programs.items():
                p=bin_dir/name;p.write_text(body);p.chmod(0o755)
            script=root/'apply.sh'
            source=Path(__file__).with_name('apply-device-profile.sh').read_text()
            script.write_text(source.replace('cd /opt/sammoy/sammoy2','cd '+str(root)).replace('/run/sammoy2-admin',str(root)))
            result=subprocess.run(['/bin/sh',str(script)],env={**os.environ,'PATH':str(bin_dir)+':'+os.defpath,'TEST_LOG':str(log)},stdout=subprocess.DEVNULL)
            self.assertNotEqual(result.returncode,0)
            commands=log.read_text().splitlines()
            self.assertEqual(commands[-1],'start sammoy2-wash-engine')
            self.assertFalse(any(s.endswith('io-helper wash-engine') for s in commands))
            self.assertEqual((root/'.hardware-profile').read_text(),'factory-only\n')

    def test_hardware_action_does_not_use_reset_or_stop_reports(self):
        with patch.object(agent,'run') as run:
            agent.perform('hardware')
        command=run.call_args.args[0]
        self.assertIn('/usr/bin/timeout',command)
        self.assertEqual(command[-1],str(agent.ROOT/'deploy/apply-commissioning-profile.py'))
        self.assertEqual(run.call_count,1)

    def test_shared_socket_directory_survives_either_service_restart(self):
        for name in ('sammoy2-admin-network.service','sammoy2-admin-system.service'):
            source=Path(__file__).with_name(name).read_text()
            self.assertIn('RuntimeDirectory=sammoy2-admin\n',source)
            self.assertIn('RuntimeDirectoryPreserve=yes\n',source)

    def test_installer_can_start_stopped_factory_helper_before_applying_profile(self):
        for target in ('wash','dry_fog'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as d:
                root=Path(d);bin_dir=root/'bin';bin_dir.mkdir()
                (root/'.hardware-profile').write_text('factory-only\n')
                (root/'.hardware-profile.before-factory-reset').write_text('full\n')
                log=root/'commands'
                programs={
                    'id':'#!/bin/sh\necho 0\n',
                    'python3':'#!/bin/sh\ncat >/dev/null\n[ "$#" != 1 ] || echo "$TEST_TARGET"\nexit 0\n',
                    'docker':'#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_LOG"\nexit 0\n'}
                for name,body in programs.items():
                    p=bin_dir/name;p.write_text(body);p.chmod(0o755)
                script=root/'apply.sh'
                source=Path(__file__).with_name('apply-device-profile.sh').read_text()
                script.write_text(source.replace('cd /opt/sammoy/sammoy2','cd '+str(root)).replace('/run/sammoy2-admin',str(root)))
                subprocess.run(['/bin/sh',str(script)],env={**os.environ,'PATH':str(bin_dir)+':'+os.defpath,'TEST_TARGET':target,'TEST_LOG':str(log)},check=True,stdout=subprocess.DEVNULL)
                commands=log.read_text().splitlines()
                stop=next(i for i,s in enumerate(commands) if s.startswith('stop sammoy2-wash-engine'))
                helper=next(i for i,s in enumerate(commands) if ' up ' in s and s.endswith('io-helper'))
                proof=next(i for i,s in enumerate(commands) if s.startswith('exec sammoy2-io-helper'))
                engine=next(i for i,s in enumerate(commands) if s.endswith('io-helper wash-engine'))
                self.assertLess(stop,helper);self.assertLess(helper,proof);self.assertLess(proof,engine)
                self.assertEqual((root/'.hardware-profile').read_text(),('full' if target=='wash' else 'dry-fog')+'\n')

    def test_no_arbitrary_action_or_profile(self):
        for value in ({'action':'sh','request_id':'x','actor':'a'}, {'action':'reboot;shutdown','request_id':'x','actor':'a'}):
            with self.assertRaises(ValueError):agent.validate(value)
        with self.assertRaises(ValueError):agent.compose('../../oops')

    def test_reset_failure_leaves_everything_stopped_and_profile_intact(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.hardware-profile').write_text('dry-fog\n')
            calls=[]
            def run(command):
                calls.append(command)
                if 'app.system_reset' in command:raise RuntimeError('busy')
            with patch.object(agent,'ROOT',root),patch.object(agent,'run',side_effect=run):
                with self.assertRaises(RuntimeError):agent.perform('full')
            self.assertEqual((root/'.hardware-profile').read_text(),'dry-fog\n')
            self.assertEqual(len(calls),3)
            self.assertEqual(calls[0][-2:],['wash-engine','telegram-reports'])
            self.assertEqual(calls[1][-1],'io-helper')

    def test_full_reset_uses_factory_profile_and_fixed_container_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.hardware-profile').write_text('dry-fog\n')
            with patch.object(agent,'ROOT',root),patch.object(agent,'run') as run:
                agent.perform('full')
            self.assertEqual((root/'.hardware-profile').read_text(),'factory-only\n')
            self.assertEqual((root/'.hardware-profile.before-factory-reset').read_text(),'dry-fog\n')
            self.assertEqual(run.call_args_list[-2].args[0],[str(root/'deploy/start-post.sh')])
            self.assertEqual(run.call_args.args[0],['/usr/bin/python3',str(root/'deploy/storage-maintenance.py'),'--reset'])
            self.assertFalse(any(isinstance(a,str) and a=='sh' for c in run.call_args_list for a in c.args[0]))

    def test_status_receipt_is_read_only_and_does_not_disclose_actor(self):
        import json
        from uuid import uuid4
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'state';request_id=str(uuid4())
            state.write_text(json.dumps({'request_id':request_id,'action':'full','status':'completed','actor':'private-admin','boot_id':'private-boot'}))
            with patch.object(agent,'STATE',state):
                code,value=agent.job_status(request_id)
                self.assertEqual(code,200);self.assertEqual(value['status'],'completed')
                self.assertNotIn('actor',value);self.assertNotIn('boot_id',value)
                self.assertEqual(agent.job_status(str(uuid4()))[0],404)
                with self.assertRaises(ValueError):agent.job_status('../state')
            self.assertIn('private-admin',state.read_text())

    def test_settings_reset_keeps_hardware_profile(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.hardware-profile').write_text('dry-fog\n')
            with patch.object(agent,'ROOT',root),patch.object(agent,'run') as run:agent.perform('settings')
            self.assertEqual((root/'.hardware-profile').read_text(),'dry-fog\n')
            self.assertEqual(len(run.call_args_list),4)


if __name__=='__main__':unittest.main()
