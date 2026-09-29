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
        broken.read_passive_target.side_effect = OSError("disconnected")
        healthy = MagicMock()
        healthy.firmware_version = (50, 1, 6, 7)

        def detect(**kwargs):
            self.assertTrue(reader.snapshot()["online"])
            self.assertIsNone(reader.snapshot()["last_error"])
            stop.set()
            return b"\x02\xAC"

        healthy.read_passive_target.side_effect = detect
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


if __name__ == "__main__":
    unittest.main()
