import io,sqlite3,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import backup
class BackupTests(unittest.TestCase):
    def test_archive_cannot_escape_or_create_symlink(self):
        for name,kind in [('../outside',tarfile.REGTYPE),('/outside',tarfile.REGTYPE),('link',tarfile.SYMTYPE),('pipe',tarfile.FIFOTYPE)]:
            b=io.BytesIO()
            with tarfile.open(fileobj=b,mode='w') as a:
                info=tarfile.TarInfo(name);info.type=kind;a.addfile(info)
            b.seek(0)
            with tarfile.open(fileobj=b) as a,self.assertRaises(RuntimeError):list(backup.safe_members(a))
    def test_sqlite_restore_reads_existing_counter_without_changing_it(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'nv9.sqlite3'
            with sqlite3.connect(p) as c:c.execute('CREATE TABLE counter(id INTEGER,stream TEXT,total INTEGER)');c.execute("INSERT INTO counter VALUES(1,'abc',10)")
            before=backup.sha(p);self.assertEqual(backup.journal(p),{'stream':'abc','total':10});self.assertEqual(before,backup.sha(p))
    def test_existing_destination_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d,patch.object(backup,'compose') as docker:
            with self.assertRaises(RuntimeError):backup.backup(Path(d))
            docker.assert_not_called()
