import importlib.util,unittest
spec=importlib.util.spec_from_file_location('nfc_bus','deploy/install-nfc-bus.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class NfcBusTests(unittest.TestCase):
 def test_only_default_entry_changes_and_retry_is_idempotent(self):
  text='default l0\nlabel l0\n linux /boot/vmlinuz-5.15.147-21-a733\n append root=uuid\nlabel rescue\n linux /boot/rescue\n'
  actual=m.update(text);self.assertEqual(actual.split('label rescue')[1],text.split('label rescue')[1]);self.assertEqual(m.update(actual),actual)
 def test_existing_overlays_are_preserved(self):
  text='default l0\nlabel l0\n linux /boot/vmlinuz-5.15.147-21-a733\n fdtoverlays /boot/other.dtbo\n'
  self.assertIn('/boot/other.dtbo '+m.OVERLAY,m.update(text))
 def test_unknown_kernel_or_default_rejected(self):
  for text in ['label l0\n linux /boot/kernel\n','default l0\nlabel l0\n linux /boot/new-kernel\n']:
   with self.assertRaises(ValueError):m.update(text)
