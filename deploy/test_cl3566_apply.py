import importlib.util
from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('cl_apply',Path(__file__).with_name('apply-cl3566-profile.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ApplyGuards(unittest.TestCase):
    def test_no_confirmation_or_missing_resource_never_stops_services(self):
        for selected,ready in ((None,True),('cubie-a7a',True),('cl3566-a-e',False)):
            with patch.object(m,'board',return_value=selected),patch.object(m,'ready',return_value=ready),patch.object(m,'run') as run:
                with self.assertRaises(RuntimeError):m.apply()
                run.assert_not_called()

    def test_funded_or_pending_session_never_stops_services(self):
        for field in ('creditSum','activeSessionId','walletTransferPending','requestedOutput'):
            with patch.object(m,'board',return_value='cl3566-a-e'),patch.object(m,'ready',return_value=True),patch.object(m,'get',return_value={'state':{field:1}}),patch.object(m,'run') as run:
                with self.assertRaises(RuntimeError):m.apply()
                run.assert_not_called()

    def test_dry_fog_requires_wallet_inventory(self):
        values=[{'state':{}},{'requested':{'type':'dry_fog'}},{'configuration':{'device_wallet_enabled':False}}]
        with patch.object(m,'board',return_value='cl3566-a-e'),patch.object(m,'ready',return_value=True),patch.object(m,'get',side_effect=values),patch.object(m,'run') as run:
            with self.assertRaises(RuntimeError):m.apply()
            run.assert_not_called()
