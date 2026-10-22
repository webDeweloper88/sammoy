"""PN532 reader lifecycle and the RFID API payload shared with wash-engine."""

import threading
import time
from collections import deque
from datetime import datetime, timezone

from pn532_linux import LinuxI2cPn532


class RfidReader:
    def __init__(self, config):
        self.enabled = bool(config.get("enabled", False))
        self.bus = int(config.get("bus", 7))
        self.address = int(config.get("address", 0x24))
        self.poll_timeout = float(config.get("poll_timeout_seconds", 0.25))
        self.release_timeout = float(config.get("release_timeout_seconds", 0.75))
        self.lock = threading.Lock()
        self.events = deque(maxlen=int(config.get("events_max", 100)))
        self.seq = 0
        self.held_uid = None
        self.last_seen = None
        self.state = {
            "enabled": self.enabled,
            "online": False,
            "bus": self.bus,
            "address": self.address,
            "firmware": None,
            "latest": None,
            "present": False,
            "last_seen_at": None,
            "last_error": "PN532 reader is starting" if self.enabled else None,
        }

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def events_since(self, since=0, limit=50):
        with self.lock:
            # A service restart resets sequence numbers. Return the new stream
            # so a running wash-engine can establish its new cursor.
            if since > self.seq:
                since = 0
            selected = [dict(event) for event in self.events if event["seq"] > since][:limit]
            return {
                "ok": True,
                "events": selected,
                "last_seq": selected[-1]["seq"] if selected else self.seq,
                "rfid": dict(self.state),
            }

    def observe(self, uid, sak=None, atqa=None):
        now = time.monotonic()
        seen_at = datetime.now(timezone.utc).isoformat()
        with self.lock:
            if uid:
                normalized = bytes(uid).hex().upper()
                if normalized != self.held_uid:
                    self.seq += 1
                    self.events.append({
                        "seq": self.seq, "time": seen_at,
                        "uid": normalized, "kind": "card_seen",
                        "sak": sak, "atqa": atqa,
                    })
                self.held_uid = normalized
                self.last_seen = now
                self.state.update(
                    latest={"uid": normalized, "seen_at": seen_at, "sak": sak, "atqa": atqa},
                    present=True, last_seen_at=seen_at, last_error=None,
                )
            elif self.last_seen is not None and now - self.last_seen >= self.release_timeout:
                self.held_uid = None
                self.last_seen = None
                self.state["present"] = False

    def run(self, stop_event):
        while self.enabled and not stop_event.is_set():
            reader = None
            try:
                reader = LinuxI2cPn532(self.bus, self.address)
                firmware = reader.firmware_version
                reader.SAM_configuration()
                with self.lock:
                    self.state.update(
                        online=True, last_error=None,
                        firmware=".".join(str(part) for part in firmware[1:]),
                    )
                print(f"PN532 ONLINE: /dev/i2c-{self.bus}, address 0x{self.address:02X}, firmware {firmware}", flush=True)
                while not stop_event.is_set():
                    target = reader.read_target_info(timeout=self.poll_timeout)
                    self.observe(**target) if target else self.observe(None)
            except Exception as exc:
                error = f"PN532 reader failed: {exc}"
                with self.lock:
                    changed = self.state["last_error"] != error
                    self.state.update(online=False, present=False, last_error=error)
                    self.held_uid = None
                    self.last_seen = None
                if changed:
                    print(error, flush=True)
            finally:
                if reader is not None:
                    try:
                        reader.close()
                    except Exception:
                        pass
                with self.lock:
                    self.state.update(online=False, present=False)
            if stop_event.wait(1.0):
                break
