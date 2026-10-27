import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('board_profiles', Path(__file__).with_name('board_profiles.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BoardProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'etc/labrix/board-profile.json'

    def file(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def cubie(self):
        self.file('proc/device-tree/compatible', b'radxa,cubie-a7a\0')

    def cl(self):
        self.file('proc/cmdline', b'quiet androidboot.hw_rev=CL3566-A-V3.0 rw')
        (self.root / 'sys/bus/platform/drivers/jwsioc_gpio/jwsioc_a').mkdir(parents=True)

    def test_unknown_does_not_default_to_cubie(self):
        self.file('proc/device-tree/model', b'Rockchip RK3566 EVB2\0')
        self.file('dev/ttyS7', b'')
        result = b.inspect(self.root, self.state)
        self.assertEqual(result['detection']['status'], 'unknown')
        self.assertIsNone(result['selection'])
        self.assertFalse(self.state.exists())

    def test_detection_never_confirms(self):
        self.cubie()
        self.assertEqual(b.detect(self.root)['suggested_board'], 'cubie-a7a')
        self.assertIsNone(b.inspect(self.root, self.state)['selection'])
        self.assertFalse(self.state.exists())

    def test_cl_requires_both_revision_and_driver(self):
        self.file('proc/cmdline', b'androidboot.hw_rev=CL3566-A-V3.0')
        self.assertEqual(b.detect(self.root)['status'], 'unknown')
        self.cl()
        self.assertEqual(b.detect(self.root)['suggested_board'], 'cl3566-a-e')

    def test_conflicting_evidence_is_refused(self):
        self.cl(); self.cubie()
        d = b.detect(self.root)
        self.assertEqual(d['status'], 'ambiguous')
        with self.assertRaises(ValueError):
            b.confirm('cubie-a7a', d, self.state)

    def test_manual_unknown_confirmation_is_explicit(self):
        s = b.confirm('cl3566-a-e', b.detect(self.root), self.state)
        self.assertEqual(s['method'], 'manual')
        self.assertEqual(b.load_selection(self.state), s)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_wrong_model_and_unknown_ids_are_refused(self):
        self.cubie()
        for name in ('cl3566-a-e', '../../bad'):
            with self.assertRaises(ValueError):
                b.confirm(name, b.detect(self.root), self.state)
        self.assertFalse(self.state.exists())

    def test_confirmation_survives_detection_change_without_rewrite(self):
        self.cl()
        original = b.confirm('cl3566-a-e', b.detect(self.root), self.state)
        saved = self.state.read_bytes()
        self.file('proc/cmdline', b'')
        self.assertEqual(b.inspect(self.root, self.state)['selection'], original)
        self.assertEqual(b.confirm('cl3566-a-e', b.detect(self.root), self.state), original)
        with self.assertRaises(ValueError):
            b.confirm('cubie-a7a', b.detect(self.root), self.state)
        self.assertEqual(self.state.read_bytes(), saved)

    def test_corrupt_state_never_falls_back_to_detection(self):
        self.cubie(); self.file('etc/labrix/board-profile.json', b'{}')
        with self.assertRaises(ValueError):
            b.inspect(self.root, self.state)

    def test_symlink_record_is_refused(self):
        p = self.root / 'record'; p.write_text('{}')
        self.state.parent.mkdir(parents=True)
        self.state.symlink_to(p)
        with self.assertRaises(ValueError):
            b.load_selection(self.state)

    def test_catalog_is_independent_and_returns_copies(self):
        p = b.profile('cubie-a7a'); p['nfc']['bus'] = 99
        self.assertEqual(b.profile('cubie-a7a')['nfc']['bus'], 7)
        self.assertEqual(b.profile('cl3566-a-e')['application_integration'], 'pending')
        self.assertNotIn('device_type', p)


if __name__ == '__main__':
    unittest.main()
