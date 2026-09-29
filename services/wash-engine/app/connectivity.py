from __future__ import annotations

from datetime import UTC, datetime
import threading
from typing import Any


class GatewayConnectivity:
    def __init__(self, *, offline_threshold: int = 3, online_threshold: int = 2) -> None:
        self.offline_threshold = max(1, offline_threshold)
        self.online_threshold = max(1, online_threshold)
        self.lock = threading.Lock()
        self.gateway_url = ""
        self.online = False
        self.initialized = False
        self.successes = 0
        self.failures = 0
        self.checked_at: str | None = None
        self.latency_ms: int | None = None
        self.error = "not checked"

    def observe(
        self,
        *,
        gateway_url: str,
        success: bool,
        latency_ms: int | None = None,
        error: str = "",
    ) -> tuple[bool, bool] | None:
        normalized_url = gateway_url.rstrip("/")
        with self.lock:
            if normalized_url != self.gateway_url:
                self.gateway_url = normalized_url
                self.online = False
                self.initialized = False
                self.successes = 0
                self.failures = 0

            previous = self.online
            was_initialized = self.initialized
            self.checked_at = datetime.now(UTC).isoformat()
            self.latency_ms = latency_ms if success else None
            self.error = "" if success else (error or "gateway unavailable")[:160]

            if success:
                self.successes += 1
                self.failures = 0
            else:
                self.failures += 1
                self.successes = 0

            if not self.initialized:
                self.online = success
                self.initialized = True
            elif self.online and self.failures >= self.offline_threshold:
                self.online = False
            elif not self.online and self.successes >= self.online_threshold:
                self.online = True

            if was_initialized and self.online != previous:
                return previous, self.online
            return None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "internetOnline": self.online,
                "internetCheckedAt": self.checked_at,
                "internetLatencyMs": self.latency_ms,
            }
