import tempfile
import unittest
from pathlib import Path

from app.main import read_microsd_cid


class HardwareIdentityTests(unittest.TestCase):
    def test_finds_cid_when_kernel_assigns_mmcblk1(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cid_path = root / "mmcblk1" / "device" / "cid"
            cid_path.parent.mkdir(parents=True)
            cid_path.write_text("0353445343363447809D5912AA0195AB\n", encoding="utf-8")
            self.assertEqual(
                read_microsd_cid([root]),
                "0353445343363447809d5912aa0195ab",
            )

    def test_supports_future_mmcblk_number_without_code_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cid_path = root / "mmcblk2" / "device" / "cid"
            cid_path.parent.mkdir(parents=True)
            cid_path.write_text("future-card-cid", encoding="utf-8")
            self.assertEqual(read_microsd_cid([root]), "future-card-cid")


if __name__ == "__main__":
    unittest.main()

class IdentitySchemeCompatibilityTests(unittest.TestCase):
    def test_legacy_hashes_unchanged(self):
        from unittest.mock import patch
        from app import main
        import hashlib
        config = {'site_code': 'demo', 'post_no': 2}
        wlan = '001122334455'
        cid = '1234567890abcdef1234567890abcdef'
        with patch.object(main, 'read_first_text_file', return_value='00:11:22:33:44:55'), \
             patch.object(main, 'read_microsd_cid', return_value=cid), \
             patch.object(main, 'selected_board', return_value='cubie-a7a'):
            value = main.get_hardware_identity(config)
        expected = lambda kind, data: hashlib.sha256(f'demo:2:{kind}:{data}'.encode()).hexdigest()
        self.assertEqual(value['hardware_fingerprint_hash'], expected('hardware_fingerprint', wlan+':'+cid))
        self.assertEqual(value['wlan0_mac_hash'], expected('wlan0_mac', wlan))
        self.assertEqual(value['microsd_cid_hash'], expected('microsd_cid', cid))

    def test_bad_selection_never_falls_back_to_legacy(self):
        from unittest.mock import patch
        from app import main
        with patch.object(main, 'selected_board', side_effect=ValueError('bad record')), \
             patch.object(main, 'read_microsd_cid') as legacy:
            value = main.get_hardware_identity({'site_code':'demo'})
        self.assertFalse(value['complete'])
        legacy.assert_not_called()
