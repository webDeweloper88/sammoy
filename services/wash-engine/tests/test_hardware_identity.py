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
