import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('apply_commissioning',Path(__file__).parents[1]/'apply-commissioning-profile.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)


class ApplyCommissioningTests(unittest.TestCase):
    def test_closed_or_funded_installation_cannot_change_hardware(self):
        for complete,credit in ((True,0),(False,1)):
            def read(path):
                return {'commissioning':{'complete':complete}} if path=='commissioning/status' else {'state':{'creditSum':credit}}
            with patch.object(helper,'get',side_effect=read),patch.object(helper.subprocess,'run') as run:
                with self.assertRaises(RuntimeError):helper.apply()
                run.assert_not_called()

    def test_missing_usb_does_not_stop_any_service(self):
        def read(path):
            return {'commissioning':{'complete':False}} if path=='commissioning/status' else {'state':{}}
        with patch.object(helper,'get',side_effect=read),patch.object(Path,'is_char_device',return_value=False),patch.object(helper.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):helper.apply()
            run.assert_not_called()

    def test_idle_installation_runs_only_the_fixed_profile_script(self):
        def read(path):
            return {'commissioning':{'complete':False}} if path=='commissioning/status' else {'state':{}}
        with patch.object(helper,'get',side_effect=read),patch.object(Path,'is_char_device',return_value=True),patch.object(helper.subprocess,'run') as run:
            helper.apply()
            run.assert_called_once_with(['/bin/sh',str(helper.ROOT/'deploy/apply-device-profile.sh')],check=True)
