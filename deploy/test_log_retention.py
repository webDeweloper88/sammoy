import importlib.util
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('log_retention','deploy/log-retention.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
    def test_calendar_month_boundaries(self):
        for now,expected in [('2026-03-31','2026-02-28'),('2024-03-31','2024-02-29'),('2026-01-15','2025-12-15')]:
            self.assertEqual(m.previous_month(datetime.fromisoformat(now)).date().isoformat(),expected)
    def test_only_journal_and_unused_old_build_cache(self):
        with patch.object(m.subprocess,'run') as run:m.main()
        args=[x.args[0] for x in run.call_args_list]
        self.assertEqual(args[0],['journalctl','--rotate'])
        self.assertIn('--vacuum-size=256M',args[1]);self.assertEqual(args[2],['/usr/bin/python3','/opt/sammoy/sammoy2/deploy/storage-maintenance.py'])
