import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

HERE = Path(__file__).parent / 'windows'
spec = importlib.util.spec_from_file_location('golden_builder', HERE / 'Build-GoldenImage.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class OfflineScrubTests(unittest.TestCase):
    def test_scrub_does_not_fill_filesystem_or_depend_on_reserved_free_counter(self):
        outcomes = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, stdout='\r0/3000/4096\n')]
        with patch.object(builder.subprocess, 'run', side_effect=outcomes), \
             patch.object(builder.os, 'write', side_effect=AssertionError('Must not fill filesystem')), \
             patch.object(builder.os, 'statvfs', side_effect=AssertionError('Reserved free count is not an exhaustion test')):
            builder.zero_free('/dev/loop-fixture', Path('/unused'), tool='/trusted/zerofree')

    def test_nonzero_free_block_verification_refuses_success(self):
        outcomes = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, stdout='7/3000/4096\n')]
        with patch.object(builder.subprocess, 'run', side_effect=outcomes):
            with self.assertRaisesRegex(RuntimeError, 'still nonzero'):
                builder.zero_free('/dev/loop-fixture', Path('/unused'), tool='/trusted/zerofree')

    def test_rw_mounted_filesystem_never_scrubbed(self):
        with patch.object(builder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as command:
            with self.assertRaisesRegex(RuntimeError, 'unmounted'):
                builder.zero_free('/dev/loop-fixture', Path('/unused'), tool='/trusted/zerofree')
            self.assertEqual(command.call_count, 1)


if __name__ == '__main__':
    unittest.main()
