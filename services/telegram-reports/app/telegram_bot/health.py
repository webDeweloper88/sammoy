from __future__ import annotations

from dataclasses import dataclass

from app.telegram_bot.store import PairingStore


@dataclass(frozen=True)
class HealthEvent:
    subject: str
    kind: str
    failures: int


class HealthTracker:
    def __init__(self, store: PairingStore, failure_threshold: int):
        self.store = store
        self.failure_threshold = max(1, failure_threshold)

    def observe(self, subject: str, online: bool) -> HealthEvent | None:
        status_key = self._key(subject, "status")
        failures_key = self._key(subject, "failures")
        previous = self.store.state(status_key) or "unknown"

        if online:
            self.store.set_state(failures_key, "0")
            if previous == "offline":
                return HealthEvent(subject, "recovered", 0)
            if previous == "unknown":
                self.store.set_state(status_key, "online")
            return None

        failures = self._failures(failures_key) + 1
        self.store.set_state(failures_key, str(failures))
        if failures >= self.failure_threshold and previous != "offline":
            return HealthEvent(subject, "offline", failures)
        return None

    def acknowledge(self, event: HealthEvent) -> None:
        status = "offline" if event.kind == "offline" else "online"
        self.store.set_state(self._key(event.subject, "status"), status)

    def _failures(self, key: str) -> int:
        value = self.store.state(key)
        try:
            return int(value) if value is not None else 0
        except ValueError:
            return 0

    @staticmethod
    def _key(subject: str, field: str) -> str:
        return f"health:{subject}:{field}"
