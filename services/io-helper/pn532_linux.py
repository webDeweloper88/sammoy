from __future__ import annotations

import time

from adafruit_pn532.adafruit_pn532 import BusyError, PN532
from smbus2 import SMBus, i2c_msg


class LinuxI2cPn532(PN532):
    """PN532 transport for a Linux /dev/i2c-* adapter."""

    def __init__(self, bus: int, address: int = 0x24) -> None:
        self._bus = SMBus(bus)
        self._address = address
        try:
            super().__init__(debug=False, irq=None, reset=None)
        except Exception:
            self._bus.close()
            raise

    def read_target_info(self, timeout: float = 1):
        """Keep ISO14443A activation metadata from the same response as UID."""
        if not self.listen_for_passive_target(timeout=timeout):
            return None
        response = self.process_response(0x4A, response_length=64, timeout=timeout)
        if response is None:
            return None
        if len(response) < 6 or response[0] != 1:
            raise RuntimeError("Invalid PN532 target response")
        length = response[5]
        if length not in (4, 7, 10) or len(response) < 6 + length:
            raise RuntimeError("Invalid PN532 UID length")
        return {"uid": bytes(response[6:6 + length]),
                "sak": int(response[4]), "atqa": bytes(response[2:4]).hex().upper()}

    def close(self) -> None:
        self._bus.close()

    def _wakeup(self) -> None:
        # The kiosk powers PN532 continuously and does not wire H_Request or
        # reset. SAM_configuration() is issued explicitly after construction.
        self.low_power = False

    def _wait_ready(self, timeout: float = 1) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = i2c_msg.read(self._address, 1)
                self._bus.i2c_rdwr(message)
                if list(message)[0] == 0x01:
                    return True
            except OSError:
                pass
            time.sleep(0.01)
        return False

    def _read_data(self, count: int) -> bytearray:
        message = i2c_msg.read(self._address, count + 1)
        self._bus.i2c_rdwr(message)
        data = bytes(message)
        if not data or data[0] != 0x01:
            raise BusyError
        return bytearray(data[1:])

    def _write_data(self, framebytes: bytes) -> None:
        try:
            self._bus.i2c_rdwr(i2c_msg.write(self._address, framebytes))
        except OSError as exc:
            # The base class hides OSError behind "Failed to detect PN532".
            raise RuntimeError(f"I2C write to 0x{self._address:02X} failed: {exc}") from exc
