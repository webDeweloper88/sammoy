import hashlib,importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('working_copy',Path(__file__).parent/'windows/Create-WorkingCopy.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class WorkingCopyTests(unittest.TestCase):
    def test_sparse_measurement_and_copy_agree_even_with_trailing_hole(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);source=p/'source';target=p/'copy'
            data=b'X'+bytes(module.CHUNK-1)+bytes(module.CHUNK*4)
            source.write_bytes(data)
            checksum,allocated=module.digest(source,'Measure',measure_sparse=True)
            self.assertEqual(checksum,hashlib.sha256(data).hexdigest())
            self.assertEqual(allocated,module.CHUNK)
            module.verified_copy(source,target,checksum)
            self.assertEqual(target.read_bytes(),data)
            self.assertLessEqual(target.stat().st_blocks*512,allocated)

    def test_budget_uses_real_windows_space_and_preserves_build_reserve(self):
        gib=1024**3
        self.assertEqual(module.check_space(17*gib,900*gib,54*gib),41*gib)
        for linux,windows in ((900,40),(40,900)):
            with self.assertRaises(RuntimeError):module.check_space(17*gib,linux*gib,windows*gib)

    def test_copy_is_independent_hash_verified_and_source_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);source=p/'original.img';partial=p/'work.partial'
            original=b'private source'+b'\0'*1048576+b'end';source.write_bytes(original)
            expected=hashlib.sha256(original).hexdigest()
            module.verified_copy(source,partial,expected)
            self.assertEqual(partial.read_bytes(),original)
            self.assertEqual(partial.stat().st_mode&0o777,0o600)
            partial.write_bytes(b'working changes')
            self.assertEqual(source.read_bytes(),original)
    def test_failed_copy_or_existing_target_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);source=p/'original.img';source.write_bytes(b'keep')
            with self.assertRaises(RuntimeError):module.verified_copy(source,p/'bad.partial','0'*64)
            self.assertEqual(source.read_bytes(),b'keep')
            with self.assertRaises(ValueError):module.verified_copy(source,source,hashlib.sha256(b'keep').hexdigest())
            self.assertEqual(source.read_bytes(),b'keep')
    def test_sidecar_checks_hash_and_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'source.img';h='a'*64
            Path(str(p)+'.sha256').write_text(h+'  source.img\n')
            self.assertEqual(module.read_expected(p),h)
            Path(str(p)+'.sha256').write_text(h+'  different.img\n')
            with self.assertRaises(ValueError):module.read_expected(p)
    def test_layout_refuses_wrong_table_or_offsets(self):
        valid={'partitiontable':{'label':'gpt','sectorsize':512,'partitions':[{'start':32768,'size':32768},{'start':65536,'size':614400},{'start':679936,'size':124055519}]}}
        module.validate_layout(valid,63864569856)
        with self.assertRaises(ValueError):module.validate_layout(valid,1000)
        valid['partitiontable']['partitions'][0]['start']=1
        with self.assertRaises(ValueError):module.validate_layout(valid,63864569856)
