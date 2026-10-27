import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from bill_vendor_gpio import VendorSysfsLine, read_level
from bill_process_reader import VendorProcessLevelReader


class VendorGpioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.mode=Path(self.tmp.name)/'mode';self.value=Path(self.tmp.name)/'value'
        self.mode.write_text('0\n');self.value.write_text('1\n')
        self.patches=[patch('bill_vendor_gpio.MODE',str(self.mode)),patch('bill_vendor_gpio.VALUE',str(self.value))]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def test_read_only_open_close_and_direction_change(self):
        line=VendorSysfsLine();self.addCleanup(line.release)
        self.assertEqual(line.get_value(),1)
        with self.assertRaises(OSError):os.write(line.fd,b'0')
        self.value.write_text('0\n');self.assertEqual(line.get_value(),0)
        self.mode.write_text('1\n')
        with self.assertRaises(RuntimeError):line.get_value()
        line.release();line.release()

    def test_invalid_values_and_missing_files_are_not_inactive(self):
        for value in ('','2\n','x'):
            self.value.write_text(value)
            with self.assertRaises(RuntimeError):VendorSysfsLine()
        self.value.unlink()
        with self.assertRaises(FileNotFoundError):VendorSysfsLine()

    def test_wrong_mode_cannot_start_and_no_mode_write(self):
        self.mode.write_text('1\n')
        with self.assertRaises(RuntimeError):VendorSysfsLine()
        self.assertEqual(self.mode.read_text(),'1\n')

    def test_symlink_is_refused(self):
        other=Path(self.tmp.name)/'other';other.write_text('1\n')
        self.value.unlink();self.value.symlink_to(other)
        with self.assertRaises(OSError):VendorSysfsLine()

    def test_actual_child_reads_sysfs_and_closes_on_mode_fault(self):
        line=VendorSysfsLine();self.addCleanup(line.release)
        reader=VendorProcessLevelReader(line,True,False,time.monotonic(),25)
        self.addCleanup(reader.close);reader.start()
        self.value.write_text('0\n')
        deadline=time.monotonic()+1;event=None
        while time.monotonic()<deadline:
            event=reader.read()
            if event and event.changed and event.active:break
            time.sleep(.005)
        self.assertIsNotNone(event);self.assertTrue(event.active)
        self.mode.write_text('1\n')
        deadline=time.monotonic()+1
        while time.monotonic()<deadline and not reader.error:time.sleep(.01)
        self.assertEqual(reader.error,'reader_failed')
        reader.close();self.assertIsNotNone(reader.process.poll())


if __name__=='__main__':unittest.main()
