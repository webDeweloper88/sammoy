import threading
import unittest
from unittest.mock import patch

from rfid import RfidReader
from pn532_linux import LinuxI2cPn532


class RfidTests(unittest.TestCase):
    def test_held_card_only_repeats_after_removal(self):
        reader = RfidReader({"enabled": True})
        reader.observe(b"\x01\xAB")
        reader.observe(b"\x01\xAB")
        self.assertEqual(len(reader.events_since()["events"]), 1)
        with patch("rfid.time.monotonic", return_value=reader.last_seen + 1):
            reader.observe(None)
        self.assertFalse(reader.snapshot()["present"])
        reader.observe(b"\x01\xAB")
        event = reader.events_since(1)["events"][0]
        self.assertEqual((event["seq"], event["uid"]), (2, "01AB"))

    def test_event_batches_and_restart_cursor(self):
        reader = RfidReader({"enabled": True})
        for value in range(4):
            reader.observe(bytes([value]))
        first = reader.events_since(0, 2)
        second = reader.events_since(first["last_seq"], 2)
        self.assertEqual([e["seq"] for e in first["events"] + second["events"]], [1, 2, 3, 4])
        self.assertEqual(reader.events_since(999)["events"][0]["seq"], 1)

    def test_disconnect_closes_reader_then_recovers(self):
        reader = RfidReader({"enabled": True})
        stop = threading.Event()
        from unittest.mock import MagicMock
        broken = MagicMock()
        broken.firmware_version = (50, 1, 6, 7)
        broken.read_target_info.side_effect = OSError("disconnected")
        healthy = MagicMock()
        healthy.firmware_version = (50, 1, 6, 7)

        def detect(**kwargs):
            self.assertTrue(reader.snapshot()["online"])
            self.assertIsNone(reader.snapshot()["last_error"])
            stop.set()
            return {"uid": b"\x02\xAC", "sak": 8, "atqa": "0400"}

        healthy.read_target_info.side_effect = detect
        with patch("rfid.LinuxI2cPn532", side_effect=[broken, healthy]):
            reader.run(stop)
        broken.close.assert_called_once()
        healthy.close.assert_called_once()
        self.assertFalse(reader.snapshot()["online"])
        self.assertEqual(reader.snapshot()["latest"]["uid"], "02AC")

    def test_constructor_failure_releases_i2c_adapter(self):
        with patch("pn532_linux.SMBus") as bus, patch(
            "pn532_linux.PN532.__init__", side_effect=RuntimeError("not detected")
        ):
            with self.assertRaisesRegex(RuntimeError, "not detected"):
                LinuxI2cPn532(7)
            bus.return_value.close.assert_called_once()

class TargetMetadataTests(unittest.TestCase):
    def test_same_response_metadata_and_uid(self):
        from unittest.mock import Mock
        reader = object.__new__(LinuxI2cPn532)
        reader.listen_for_passive_target = Mock(return_value=True)
        reader.process_response = Mock(return_value=bytes([1, 1, 4, 0, 32, 4, 1, 2, 3, 4]))
        target = reader.read_target_info()
        self.assertEqual(target, {'uid': b'\x01\x02\x03\x04', 'sak': 32, 'atqa': '0400'})
        events = RfidReader({'enabled': True})
        events.observe(**target)
        self.assertEqual(events.events_since()['events'][0]['sak'], 32)

    def test_truncated_response_is_not_a_card(self):
        from unittest.mock import Mock
        reader = object.__new__(LinuxI2cPn532)
        reader.listen_for_passive_target = Mock(return_value=True)
        reader.process_response = Mock(return_value=bytes([1, 1, 4, 0, 8, 7, 1]))
        with self.assertRaises(RuntimeError):
            reader.read_target_info()


if __name__ == "__main__":
    unittest.main()

class HsuRfidIntegrationTests(unittest.TestCase):
    def test_hsu_transport_preserves_card_metadata_and_closes(self):
        from unittest.mock import MagicMock
        reader = RfidReader({'enabled':True,'transport':'hsu','device':'/dev/ttyS9','baud_rate':115200})
        stop=threading.Event(); device=MagicMock();device.firmware_version=(50,1,6,7)
        def poll(**kwargs):
            stop.set()
            return {'uid':bytes.fromhex('01020304'),'sak':32,'atqa':'0004'}
        device.read_target_info.side_effect=poll
        with patch('rfid.LinuxHsuPn532',return_value=device) as factory, patch('rfid.LinuxI2cPn532') as i2c:
            reader.run(stop)
        factory.assert_called_once_with('/dev/ttyS9',115200)
        i2c.assert_not_called();device.close.assert_called_once()
        event=reader.events_since()['events'][0]
        self.assertEqual((event['sak'],event['atqa'],event['uid']),(32,'0004','01020304'))

    def test_unknown_transport_does_not_fall_back_to_i2c(self):
        with self.assertRaises(ValueError):RfidReader({'transport':'typo'})
