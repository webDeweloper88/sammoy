import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('commission_helper', Path(__file__).parent / 'commission-hardware.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class HardwareCommissionTests(unittest.TestCase):
    def status(self, post=3):
        return {'site': {'post_no': post}, 'commissioning': {'complete': False}, 'io_ready': False}

    def test_wrong_post_and_active_credit_refuse_all_changes(self):
        for post, credit in ((1, 0), (3, 1000)):
            def read(path):
                return {'state': {'creditSum': credit}} if path.endswith('/state') else self.status(post)
            with patch.object(helper, 'get', side_effect=read), patch.object(helper, 'diagnosis') as probe, patch.object(helper, 'restore_orientation') as display:
                with self.assertRaises(RuntimeError):
                    helper.main(3)
                probe.assert_not_called(); display.assert_not_called()

    def test_missing_hardware_never_stops_backend(self):
        def read(path):
            return {'state': {'creditSum': 0}} if path.endswith('/state') else self.status()
        with patch.object(helper, 'get', side_effect=read), patch.object(helper, 'diagnosis', return_value={'hardware_profile':'factory-only','required_nodes':{'/dev/ttyUSB0':False}}), patch.object(helper,'restore_orientation'), patch.object(helper,'command') as command:
            helper.main(3)
            command.assert_not_called()

    def test_failed_hardware_apply_restores_installer_engine_without_reset(self):
        def read(path):
            return {'state': {'creditSum': 0}} if path.endswith('/state') else self.status()
        def command(*args, **kwargs):
            return subprocess.CompletedProcess(args, 1 if args[0]=='/bin/sh' else 0, stdout='Modbus disconnected', stderr='')
        before={'hardware_profile':'factory-only','required_nodes':{'usb':True,'gpio':True,'i2c':True}}
        after={'hardware_profile':'factory-only','io':{'modbus_ok':False}}
        with patch.object(helper,'get',side_effect=read), patch.object(helper,'diagnosis',side_effect=[before,after]), patch.object(helper,'restore_orientation'), patch.object(helper,'redact',side_effect=lambda s:s), patch.object(helper,'command',side_effect=command) as invoked:
            helper.main(3)
            self.assertTrue(any(c.args==('docker','start','sammoy2-wash-engine') for c in invoked.call_args_list))
            self.assertFalse(any('reset' in str(c.args) or 'down' in c.args for c in invoked.call_args_list))


if __name__ == '__main__':
    unittest.main()
