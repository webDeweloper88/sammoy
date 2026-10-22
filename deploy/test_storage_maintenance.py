import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('storage',Path(__file__).with_name('storage-maintenance.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class StorageTests(unittest.TestCase):
 def test_reset_preserves_data_scripts_directories_and_symlink_targets(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'release.tar').write_bytes(b'abc');(root/'money.sqlite3').write_text('keep');(root/'tool.py').write_text('keep');(root/'data.tar').mkdir();(root/'link.tar').symlink_to(root/'money.sqlite3')
   self.assertEqual(m.clear_archives(root,True),3)
   for name in ('money.sqlite3','tool.py','data.tar','link.tar'):self.assertTrue((root/name).exists())
 def test_daily_keeps_recent_upload_and_rejects_directory_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'release.tar';p.write_text('abc');now=p.stat().st_mtime
   self.assertEqual(m.clear_archives(root,False,now+3600),0)
   link=root/'cache';link.symlink_to(root,target_is_directory=True);self.assertEqual(m.clear_archives(link,True),0)
   self.assertEqual(m.clear_archives(root,False,now+172801),3)
