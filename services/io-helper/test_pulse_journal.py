import tempfile
import unittest
from pathlib import Path
from pulse_journal import PulseJournal

class PulseJournalTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'counter.sqlite3')
    def tearDown(self):self.tmp.cleanup()
    def test_reopen_preserves_stream_and_all_committed_pulses(self):
        a=PulseJournal(self.path);identity=a.stream_id
        self.assertEqual(a.increment(),1);self.assertEqual(a.increment(),2);a.close()
        b=PulseJournal(self.path);self.assertEqual(b.stream_id,identity);self.assertEqual(b.value(),2)
        self.assertEqual(b.increment(),3);b.close()
    def test_failed_write_is_not_published_or_acknowledged(self):
        a=PulseJournal(self.path)
        a.conn.execute("CREATE TRIGGER fail BEFORE UPDATE ON counter BEGIN SELECT RAISE(ABORT,'disk error'); END");a.conn.commit()
        with self.assertRaises(Exception):a.increment()
        self.assertEqual(a.value(),0);a.close()
        b=PulseJournal(self.path);self.assertEqual(b.value(),0);b.close()
    def test_corrupted_journal_never_resets_to_a_new_stream(self):
        Path(self.path).write_bytes(b'corrupted sqlite file')
        with self.assertRaises(Exception):PulseJournal(self.path)

    def test_process_exit_after_commit_does_not_lose_pulse(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-c',
            'import os,sys;from pulse_journal import PulseJournal;j=PulseJournal(sys.argv[1]);j.increment();os._exit(0)',self.path],
            cwd=Path(__file__).resolve().parent)
        self.assertEqual(result.returncode,0)
        journal=PulseJournal(self.path);self.assertEqual(journal.value(),1);journal.close()
