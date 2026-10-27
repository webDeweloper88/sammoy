import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from app.storage_identity import cl3566_identity, emmc_cid, selected_board


class StorageIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.node('mmcblk2', 'MMC', '0', '1234567890abcdef1234567890abcdef')

    def node(self, name, kind, removable, cid):
        p = self.root/name; (p/'device').mkdir(parents=True, exist_ok=True)
        (p/'device/type').write_text(kind); (p/'removable').write_text(removable)
        (p/'device/cid').write_text(cid)

    def identity(self):
        return cl3566_identity({'site_code':'test','post_no':3}, '00:11:22:33:44:55', [self.root])

    def test_sd_insertion_never_changes_identity(self):
        before = self.identity()
        self.node('mmcblk0', 'SD', '1', 'a'*32)
        self.assertEqual(before, self.identity())
        self.assertEqual(before['storage_type'], 'emmc')
        self.assertFalse(before['microsd_cid_present'])

    def test_multiple_emmc_refused_even_if_same_cid(self):
        self.node('mmcblk3','MMC','0','1234567890abcdef1234567890abcdef')
        with self.assertRaises(ValueError): self.identity()

    def test_no_emmc_does_not_fall_back_to_sd_or_other_root(self):
        (self.root/'mmcblk2/device/type').write_text('SD')
        with self.assertRaises(ValueError): self.identity()

    def test_invalid_cid_fails_closed(self):
        for cid in ('', '0'*32, 'f'*32, 'not-a-cid'):
            (self.root/'mmcblk2/device/cid').write_text(cid)
            with self.assertRaises(ValueError): self.identity()

    def test_scheme_domain_separation_and_storage_change(self):
        a = self.identity()
        expected = hashlib.sha256(b'test:3:cl3566-emmc-v1:emmc_cid:1234567890abcdef1234567890abcdef').hexdigest()
        self.assertEqual(a['microsd_cid_hash'], expected)
        (self.root/'mmcblk2/device/cid').write_text('a'*32)
        b = self.identity()
        self.assertNotEqual(a['hardware_fingerprint_hash'], b['hardware_fingerprint_hash'])
        self.assertEqual(a['wlan0_mac_hash'], b['wlan0_mac_hash'])

    def test_bad_wlan_refused(self):
        with self.assertRaises(ValueError): cl3566_identity({}, '', [self.root])

    def test_selection_requires_confirmed_known_model(self):
        p = self.root/'board.json'
        self.assertIsNone(selected_board(p))
        for d in ({}, {'schema':1,'confirmed':False,'board_id':'cl3566-a-e'}, {'schema':1,'confirmed':True,'board_id':'unknown'}):
            p.write_text(json.dumps(d))
            with self.assertRaises(ValueError):selected_board(p)
        p.write_text(json.dumps({'schema':1,'confirmed':True,'board_id':'cl3566-a-e'}))
        self.assertEqual(selected_board(p), 'cl3566-a-e')


if __name__=='__main__': unittest.main()
