import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('prepare_release',Path(__file__).with_name('prepare-software-release.py'))
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

class ReleasePreparationTests(unittest.TestCase):
    def fixture(self,folder):
        root=folder/'repo';root.mkdir();key=folder/'signing.pem';key.write_text('fixture');key.chmod(0o600)
        args=argparse.Namespace(number=3,version='2026.10.23.3',notes={'ru':'Исправление','uz':'Tuzatish','en':'Fix'},private=key,output=folder/'release',docker_command='docker',docker_binary=Path('/usr/bin/docker'),signer_image='trusted:local',plan=False)
        return root,args

    def test_metadata_rejects_invalid_or_empty_fields(self):
        for number,version,notes in [(0,'v',{'ru':'x','uz':'x','en':'x'}),(1,'bad/path',{'ru':'x','uz':'x','en':'x'}),(1,'v',{'ru':'x'}),(1,'v',{'ru':' ','uz':'x','en':'x'})]:
            with self.subTest(version=version,notes=notes),self.assertRaises(ValueError):w.metadata(number,version,notes)

    def test_plan_never_builds_or_signs(self):
        with tempfile.TemporaryDirectory() as temp:
            root,args=self.fixture(Path(temp));args.plan=True
            with patch.object(w,'source_info',return_value='commit'),patch.object(w.subprocess,'run') as run,redirect_stdout(io.StringIO()):w.prepare(args,root)
            run.assert_not_called();self.assertFalse(args.output.exists())

    def test_unsafe_key_or_existing_output_refused_before_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            root,args=self.fixture(Path(temp))
            with patch.object(w,'source_info',return_value='commit'),patch.object(w,'capture') as capture:
                args.private.chmod(0o644)
                with self.assertRaises(ValueError):w.prepare(args,root)
                args.private.chmod(0o600);args.output.mkdir()
                with self.assertRaises(ValueError):w.prepare(args,root)
                capture.assert_not_called()

    def test_export_excludes_untracked_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'repo';root.mkdir()
            def git(*args):return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
            git('init');(root/'tracked').write_text('source');git('add','tracked');git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','test')
            (root/'.env').write_text('private');dest=base/'export';dest.mkdir();source=w.export_source(root,dest)
            self.assertTrue((source/'tracked').exists());self.assertFalse((source/'.env').exists())
            with self.assertRaises(ValueError):w.source_info(root)

    def test_complete_flow_uses_release_tags_and_never_starts_services(self):
        with tempfile.TemporaryDirectory() as temp:
            root,args=self.fixture(Path(temp));commands=[]
            def export(root,destination):source=destination/'source';source.mkdir();return source
            def capture(command,**kwargs):
                return json.dumps([{'Id':'sha256:trusted'}]) if 'inspect' in command else 'aarch64'
            def run(command,**kwargs):
                commands.append(command)
                if '/work/scripts/build-software-release.py' in command:
                    workspace=Path(next(v for v in command if v.endswith(':/release')).split(':/release')[0]);result=workspace/'result';result.mkdir();(result/'release.json').write_text('{}');(result/'archive.tar.gz').write_bytes(b'fixture')
            with patch.object(w,'source_info',return_value='committed'),patch.object(w,'export_source',side_effect=export),patch.object(w,'capture',side_effect=capture),patch.object(w.subprocess,'run',side_effect=run),redirect_stdout(io.StringIO()):w.prepare(args,root)
            self.assertTrue((args.output/'release.json').exists());self.assertEqual(json.loads((args.output/'build.json').read_text())['commit'],'committed')
            builds=[c for c in commands if 'build' in c and '--platform' in c];self.assertEqual(len(builds),4)
            self.assertTrue(all(':release-' in c[c.index('-t')+1] for c in builds))
            self.assertFalse(any('compose' in c or 'push' in c for c in commands))

    def test_build_failure_leaves_no_ready_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root,args=self.fixture(Path(temp))
            def export(root,destination):source=destination/'source';source.mkdir();return source
            def run(command,**kwargs):
                if 'build' in command:raise subprocess.CalledProcessError(1,command)
            with patch.object(w,'source_info',return_value='committed'),patch.object(w,'export_source',side_effect=export),patch.object(w,'capture',side_effect=['aarch64',json.dumps([{'Id':'sha256:trusted'}])]),patch.object(w.subprocess,'run',side_effect=run),redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):w.prepare(args,root)
            self.assertFalse(args.output.exists())

    def test_signing_failure_never_promotes_partial_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root,args=self.fixture(Path(temp))
            def export(root,destination):source=destination/'source';source.mkdir();return source
            def run(command,**kwargs):
                if '/work/scripts/build-software-release.py' in command:
                    workspace=Path(next(v for v in command if v.endswith(':/release')).split(':/release')[0]);result=workspace/'result';result.mkdir();(result/'partial').write_bytes(b'partial')
                    raise subprocess.CalledProcessError(1,command)
            with patch.object(w,'source_info',return_value='committed'),patch.object(w,'export_source',side_effect=export),patch.object(w,'capture',side_effect=['aarch64',json.dumps([{'Id':'sha256:trusted'}])]),patch.object(w.subprocess,'run',side_effect=run),redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):w.prepare(args,root)
            self.assertFalse(args.output.exists())
            self.assertFalse(list(Path(temp).glob('labrix-release-*')))

    def test_private_key_inside_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root,args=self.fixture(Path(temp));args.private.rename(root/'private.pem');args.private=root/'private.pem'
            with patch.object(w,'source_info',return_value='committed'),self.assertRaisesRegex(ValueError,'outside the Git repository'):w.prepare(args,root)

if __name__=='__main__':unittest.main()
