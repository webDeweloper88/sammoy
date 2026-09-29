from __future__ import annotations

import threading
import time
from math import ceil
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from .config import settings
from .db import db
from .io_client import io_request


MODE_OUTPUTS = {"water", "foam", "chem", "nano", "wax", "vacuum", "air", "osmos"}
PROGRAM_ORDER = ["water", "foam", "air", "vacuum", "pause", "osmos", "nano", "wax", "chem"]
BILL_PULSE_SUM = 1000
COIN_PULSE_SUM = 1000
FREE_PAUSE_SECONDS = 60
TICK_SECONDS = 0.2
LEDGER_FLUSH_SECONDS = 5.0
RETENTION_DAYS = 90

DEFAULT_WASH_PARAMETERS: dict[str, Any] = {
    "version": 1,
    "billPulseSum": BILL_PULSE_SUM,
    "coinPulseSum": COIN_PULSE_SUM,
    # Shared free-pause budget for the whole wash session.
    "freePauseSeconds": FREE_PAUSE_SECONDS,

    # Free delay after releasing the Total Stop trigger.
    "triggerGraceSeconds": 1,

    # Physical trigger must remain continuously OFF for this long
    # before WEB-PAUSE restart interlock is cleared.
    "triggerResetConfirmSeconds": 0.5,

    # Separate tariff used after the free-pause budget is exhausted.
    "paidPause": {
        "enabled": True,
        "amountSum": 1000,
        "durationSeconds": 120,
    },

    # Maximum power-loss interval during which the same customer session
    # may be safely restored. Owner can change this dynamically.
    "powerRecoverySeconds": 600,

    # IN3 is the wash-gun/total-stop permission contact.  A mode may energize
    # its relay only while this input is physically active.
    "requireTotalStopTrigger": True,
    "tariffs": {
        "water": {"amountSum": 1000, "durationSeconds": 40, "enabled": True},
        "foam": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "chem": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "nano": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "wax": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "vacuum": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "air": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "osmos": {"amountSum": 1000, "durationSeconds": 20, "enabled": True},
        "pause": {"amountSum": 0, "durationSeconds": 0, "enabled": True},
    },
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict):
        if not isinstance(override, dict):
            return deepcopy(base)
        result = deepcopy(base)
        for key, value in override.items():
            result[key] = deep_merge(base.get(key), value) if key in base else deepcopy(value)
        return result
    return deepcopy(override) if override is not None else deepcopy(base)


def normalize_parameters(value: dict[str, Any] | None) -> dict[str, Any]:
    params = deep_merge(DEFAULT_WASH_PARAMETERS, value or {})
    params["billPulseSum"] = max(int(params.get("billPulseSum") or BILL_PULSE_SUM), 0)
    params["coinPulseSum"] = max(int(params.get("coinPulseSum") or COIN_PULSE_SUM), 0)
    free_pause_raw = params.get(
        "freePauseSeconds",
        FREE_PAUSE_SECONDS,
    )
    params["freePauseSeconds"] = max(
        int(
            FREE_PAUSE_SECONDS
            if free_pause_raw is None
            else free_pause_raw
        ),
        0,
    )

    trigger_grace_raw = params.get(
        "triggerGraceSeconds",
        1,
    )
    params["triggerGraceSeconds"] = max(
        int(
            1
            if trigger_grace_raw is None
            else trigger_grace_raw
        ),
        0,
    )

    trigger_reset_raw = params.get(
        "triggerResetConfirmSeconds",
        0.5,
    )
    params["triggerResetConfirmSeconds"] = max(
        float(
            0.5
            if trigger_reset_raw is None
            else trigger_reset_raw
        ),
        0.0,
    )

    paid_pause = params.get("paidPause")
    if not isinstance(paid_pause, dict):
        paid_pause = {}

    paid_pause["enabled"] = (
        paid_pause.get("enabled", True) is not False
    )

    paid_pause["amountSum"] = max(
        int(paid_pause.get("amountSum", 1000) or 0),
        0,
    )

    paid_pause["durationSeconds"] = max(
        int(paid_pause.get("durationSeconds", 120) or 0),
        0,
    )

    if paid_pause["durationSeconds"] > 0:
        paid_pause["sumPerMinute"] = int(
            round(
                paid_pause["amountSum"]
                / paid_pause["durationSeconds"]
                * 60
            )
        )
    else:
        paid_pause["sumPerMinute"] = 0

    params["paidPause"] = paid_pause

    params["powerRecoverySeconds"] = max(
        int(params.get("powerRecoverySeconds") or 600),
        0,
    )

    params["requireTotalStopTrigger"] = bool(
        params.get("requireTotalStopTrigger", True)
    )

    tariffs = params.setdefault("tariffs", {})
    for mode, default in DEFAULT_WASH_PARAMETERS["tariffs"].items():
        current = tariffs.get(mode, {})
        merged = deep_merge(default, current if isinstance(current, dict) else {})
        merged["amountSum"] = max(int(merged.get("amountSum") or default.get("amountSum") or 0), 0)
        merged["durationSeconds"] = max(int(merged.get("durationSeconds") or default.get("durationSeconds") or 0), 0)
        if merged["durationSeconds"] > 0:
            merged["sumPerMinute"] = int(round((merged["amountSum"] / merged["durationSeconds"]) * 60))
        else:
            merged["sumPerMinute"] = 0
        merged["enabled"] = merged.get("enabled") is not False
        tariffs[mode] = merged
    return params


class WashRuntime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.params = normalize_parameters(None)
        self.state: dict[str, Any] = {
            "phase": "idle",
            "creditSum": 0,
            "selectedMode": "pause",
            "armedMode": None,
            "activeMode": None,
            "requestedOutput": None,
            "totalStopActive": True,
            # Shared free-pause budget for the whole wash session.
            "freePauseRemaining": 0,
            "_pauseBudgetFloat": 0.0,
            "_pauseBudgetInitialized": False,

            # Public pause state for kiosk/Owner diagnostics.
            "pauseState": "none",

            # Stage 3 will use these for Total Stop grace/safe resume.
            "triggerGraceRemaining": 0,
            "_triggerGraceFloat": 0.0,

            "resumeRequiresTriggerReset": False,
            "_triggerResetOffFloat": 0.0,
            "triggerResetConfirmRemaining": 0.0,

            "billPulses": 0,
            "coinPulses": 0,
            "activeSessionId": None,
            "activeSessionCardUid": None,
            "lastRfidUid": None,
            "lastRfidStatus": "not_checked",
            "lastIoOk": False,
            "lastError": None,

            # Power-loss recovery state
            "powerRecoveryAvailable": False,
            "powerRecoveryDowntimeSeconds": 0,
            "powerRecoveryLimitSeconds": 0,

            "licenseLocked": False,
            "licenseReason": "not_checked",
            "license": {},
            "updatedAt": now_iso(),
        }
        self.last_tick = time.monotonic()
        self.last_mode_change = self.last_tick
        self.last_bill_pulses = 0
        self.last_coin_pulses = 0
        self.last_rfid_seq = 0
        self.last_output: str | None = None
        self.io_failures = 0
        self.active_session_id: int | None = None
        self.active_session_source = "unknown"
        self.active_session_card_uid: str | None = None
        self.active_session_initial_credit = 0
        self.active_usage_id: int | None = None
        self.active_usage_mode: str | None = None
        self.pending_usage: dict[str, float] = {"duration_ms": 0.0, "spent_sum": 0.0, "pause_ms": 0.0, "total_stop_wait_ms": 0.0}
        self.ledger_spent_carry = 0.0
        self.last_ledger_flush = time.monotonic()
        self.last_retention_cleanup = 0.0
        self.simulation: dict[str, Any] = {
            "totalStopActive": None,
            "coinPulses": 0,
            "licenseMode": "real",
            "updatedAt": None,
        }

    def start(self) -> None:
        self.stop_event.clear()
        self.load_parameters()

        # SAFETY: never restore energized equipment after restart.
        self._all_off_sync()

        # Restore customer credit only when the outage is within
        # the Owner-configured recovery window.
        self._recover_interrupted_sessions_sync()

        self._cleanup_retention_sync()
        self._baseline_pulse_counters()
        self._baseline_rfid_events()
        self.thread = threading.Thread(target=self._run, name="wash-runtime", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        try:
            with self.lock:
                self._flush_usage_locked()
        except Exception:
            pass
        finally:
            self._all_off_sync()

    def load_parameters(self) -> None:
        with db() as conn:
            row = conn.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = 'wash_parameters'",
            ).fetchone()
        with self.lock:
            self.params = normalize_parameters(row["setting_value"] if row else None)

    def save_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_parameters(params)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES ('wash_parameters', %s, now())
                ON CONFLICT (setting_key) DO UPDATE
                SET setting_value = EXCLUDED.setting_value,
                    updated_at = now()
                """,
                (Jsonb(normalized),),
            )
            conn.commit()
        with self.lock:
            self.params = normalized
        return normalized

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            state = deepcopy(self.state)
            state.pop("_creditFloat", None)
            state.pop("_pauseBudgetFloat", None)
            state.pop("_pauseBudgetInitialized", None)
            state.pop("_triggerGraceFloat", None)
            state.pop("_triggerResetOffFloat", None)
            state["activeSessionId"] = self.active_session_id
            state["activeSessionCardUid"] = self.active_session_card_uid
            return {
                "ok": True,
                "state": state,
                "parameters": deepcopy(self.params),
                "simulation": deepcopy(self.simulation),
            }

    def select_mode(self, mode: str) -> dict[str, Any]:
        if mode not in PROGRAM_ORDER:
            raise ValueError(f"Unknown wash mode: {mode}")

        with self.lock:
            if self.state.get("licenseLocked"):
                self.state["phase"] = "license_locked"
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["activeMode"] = None
                self.state["updatedAt"] = now_iso()
                raise ValueError(
                    f"License locked: "
                    f"{self.state.get('licenseReason') or 'locked'}"
                )

            tariff = self.params["tariffs"].get(mode, {})
            if tariff.get("enabled") is False:
                raise ValueError(f"Wash mode disabled: {mode}")

            credit = int(self.state.get("creditSum") or 0)

            if mode == "pause":
                self.state["selectedMode"] = "pause"
                self.state["activeMode"] = None
                self.state["requestedOutput"] = None

                # WEB PAUSE always overrides the physical trigger.
                # If PAUSE is pressed while the trigger is physically ON,
                # require an OFF -> ON cycle before equipment can restart.
                trigger_required = bool(
                    self.params.get(
                        "requireTotalStopTrigger",
                        True,
                    )
                )

                if trigger_required:
                    self.state["resumeRequiresTriggerReset"] = bool(
                        self.state.get("totalStopActive")
                    )

                    if self.state["resumeRequiresTriggerReset"]:
                        confirm = float(
                            self.params.get(
                                "triggerResetConfirmSeconds",
                                0.5,
                            )
                        )
                        self.state["_triggerResetOffFloat"] = 0.0
                        self.state["triggerResetConfirmRemaining"] = confirm
                    else:
                        self.state["_triggerResetOffFloat"] = 0.0
                        self.state["triggerResetConfirmRemaining"] = 0.0
                else:
                    self.state["resumeRequiresTriggerReset"] = False
                    self.state["_triggerResetOffFloat"] = 0.0
                    self.state["triggerResetConfirmRemaining"] = 0.0

                self.state["_triggerGraceFloat"] = 0.0
                self.state["triggerGraceRemaining"] = 0

                if credit <= 0:
                    self.state["armedMode"] = None
                    self.state["phase"] = "no_credit"
                    self.state["pauseState"] = "none"

                elif self.state.get("armedMode"):
                    # IMPORTANT:
                    # do NOT refill free-pause budget here.
                    # The same budget is shared by the entire session.
                    self._ensure_pause_budget_locked()
                    self.state["phase"] = "manual_pause"
                    self.state["pauseState"] = (
                        "free"
                        if int(
                            self.state.get(
                                "freePauseRemaining"
                            ) or 0
                        ) > 0
                        else "paid"
                    )

                else:
                    self.state["phase"] = "idle"
                    self.state["pauseState"] = "none"

            elif credit <= 0:
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["activeMode"] = None
                self.state["phase"] = "no_credit"

                self.state["freePauseRemaining"] = 0
                self.state["_pauseBudgetFloat"] = 0.0
                self.state["_pauseBudgetInitialized"] = False
                self.state["pauseState"] = "none"

            else:
                # New or existing funded session gets one shared
                # free-pause budget. Switching modes never replenishes it.
                self._ensure_pause_budget_locked()

                # Explicit mode selection accepts a recovered session.
                self.state["powerRecoveryAvailable"] = False
                self.state["powerRecoveryDowntimeSeconds"] = 0

                self.state["selectedMode"] = mode
                self.state["armedMode"] = mode
                self.state["activeMode"] = None
                self.state["phase"] = "armed"
                self.state["pauseState"] = "none"

                trigger_required = bool(
                    self.params.get(
                        "requireTotalStopTrigger",
                        True,
                    )
                )

                if not trigger_required:
                    # Winter/bypass mode:
                    # physical Total Stop is ignored by runtime logic.
                    self.state["resumeRequiresTriggerReset"] = False
                    self.state["_triggerResetOffFloat"] = 0.0
                    self.state["triggerResetConfirmRemaining"] = 0.0
                    self.state["_triggerGraceFloat"] = 0.0
                    self.state["triggerGraceRemaining"] = 0

                elif not self.state.get(
                    "resumeRequiresTriggerReset"
                ):
                    # Selecting/changing a program must never grant
                    # additional trigger grace. Grace is created only by
                    # a real physical Total Stop ON -> OFF transition
                    # inside the runtime loop.
                    self.state["_triggerGraceFloat"] = 0.0
                    self.state["triggerGraceRemaining"] = 0

                self.last_mode_change = time.monotonic()

            self.state["updatedAt"] = now_iso()

        if mode == "pause":
            self._apply_output_sync(None)

        return self.snapshot()

    def stop_wash(self) -> dict[str, Any]:
        with self.lock:
            remaining_credit = int(self.state.get("creditSum") or 0)
            close_reason = "operator_stop"
            if remaining_credit > 0 and self.active_session_source == "vip":
                close_reason = "vip_remaining_burned"
            self.state["creditSum"] = 0
            self.state["_creditFloat"] = 0.0
            if self.active_session_id:
                self._close_session_locked(close_reason)
            self.state["selectedMode"] = "pause"
            self.state["armedMode"] = None
            self.state["activeMode"] = None
            self.state["phase"] = "stopped"
            self.state["powerRecoveryAvailable"] = False
            self.state["powerRecoveryDowntimeSeconds"] = 0
            self.state["freePauseRemaining"] = 0
            self.state["_pauseBudgetFloat"] = 0.0
            self.state["_pauseBudgetInitialized"] = False
            self.state["pauseState"] = "none"
            self.state["triggerGraceRemaining"] = 0
            self.state["_triggerGraceFloat"] = 0.0
            self.state["resumeRequiresTriggerReset"] = False
            self.state["_triggerResetOffFloat"] = 0.0
            self.state["triggerResetConfirmRemaining"] = 0.0
            self.state["updatedAt"] = now_iso()
        self._all_off_sync()
        return self.snapshot()

    def add_credit(
        self,
        amount_sum: int,
        source: str = "manual",
        idempotency_key: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if self.state.get("licenseLocked") and source != "admin":
                self.state["phase"] = "license_locked"
                self.state["updatedAt"] = now_iso()
                return self.snapshot()
            if idempotency_key:
                with db() as conn:
                    existing = conn.execute(
                        "SELECT id FROM payments WHERE idempotency_key = %s",
                        (idempotency_key,),
                    ).fetchone()
                if existing:
                    return self.snapshot()
            self.state["creditSum"] = max(0, int(self.state["creditSum"]) + int(amount_sum))
            self.state["_creditFloat"] = float(self.state["creditSum"])
            self.state["lastCreditSource"] = source
            if (
                self.state["creditSum"] > 0
                and not self.state.get("armedMode")
                and not self.state.get("activeMode")
                and self.state.get("selectedMode") == "pause"
                and self.state.get("phase") in {"no_credit", "idle", "stopped", "manual_pause", "pause_free", "pause_paid"}
            ):
                self.state["phase"] = "idle"
                self.state["freePauseRemaining"] = 0
                self.state["_pauseBudgetFloat"] = 0.0
            self.state["updatedAt"] = now_iso()
            self._record_credit_locked(
                int(amount_sum),
                source,
                None,
                raw_payload or {"source": source},
                idempotency_key=idempotency_key,
            )
        return self.snapshot()

    def set_license_status(self, locked: bool, reason: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        with self.lock:
            simulated_mode = str(self.simulation.get("licenseMode") or "real")
            if simulated_mode != "real":
                if simulated_mode == "valid":
                    locked = False
                    reason = "simulation: license valid"
                    payload = {
                        **payload,
                        "enabled": True,
                        "locked": False,
                        "state": "valid",
                        "reason": reason,
                        "simulation": True,
                    }
                elif simulated_mode == "expired":
                    locked = True
                    reason = "simulation: license expired"
                    payload = {
                        **payload,
                        "enabled": False,
                        "locked": True,
                        "state": "expired",
                        "reason": reason,
                        "simulation": True,
                    }
                elif simulated_mode == "disabled":
                    locked = True
                    reason = "simulation: license disabled"
                    payload = {
                        **payload,
                        "enabled": False,
                        "locked": True,
                        "state": "disabled",
                        "reason": reason,
                        "simulation": True,
                    }
                elif simulated_mode == "sync_failed":
                    locked = True
                    reason = "simulation: license sync failed"
                    payload = {
                        **payload,
                        "enabled": False,
                        "locked": True,
                        "state": "sync_failed",
                        "reason": reason,
                        "last_error": "simulation: gateway unavailable",
                        "simulation": True,
                    }
            was_locked = bool(self.state.get("licenseLocked"))
            self.state["licenseLocked"] = bool(locked)
            self.state["licenseReason"] = reason
            self.state["license"] = payload
            if locked:
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["activeMode"] = None
                self.state["requestedOutput"] = None
                self.state["phase"] = "license_locked"
                self.state["freePauseRemaining"] = 0
                self.state["_pauseBudgetFloat"] = 0.0
            elif was_locked and self.state.get("phase") == "license_locked":
                self.state["phase"] = "no_credit" if int(self.state.get("creditSum") or 0) <= 0 else "idle"
            self.state["updatedAt"] = now_iso()
        if locked:
            self._all_off_sync()
        return self.snapshot()

    def set_simulated_total_stop(self, active: bool | None) -> dict[str, Any]:
        with self.lock:
            self.simulation["totalStopActive"] = active
            self.simulation["updatedAt"] = now_iso()
        return self.snapshot()

    def add_simulated_coin_pulses(self, count: int) -> dict[str, Any]:
        with self.lock:
            self.simulation["coinPulses"] = int(self.simulation.get("coinPulses") or 0) + int(count)
            self.simulation["updatedAt"] = now_iso()
        return self.snapshot()

    def set_simulated_license(self, mode: str) -> dict[str, Any]:
        if mode not in {"real", "valid", "expired", "disabled", "sync_failed"}:
            raise ValueError("unsupported license simulation mode")
        with self.lock:
            self.simulation["licenseMode"] = mode
            self.simulation["updatedAt"] = now_iso()
        return self.snapshot()

    def reset_simulation(self) -> dict[str, Any]:
        with self.lock:
            self.simulation["totalStopActive"] = None
            self.simulation["coinPulses"] = 0
            self.simulation["licenseMode"] = "real"
            self.simulation["updatedAt"] = now_iso()
        return self.snapshot()

    def _baseline_pulse_counters(self) -> None:
        try:
            io = self._get_io_sync()
        except Exception:
            return
        inputs_raw = io.get("inputs", {})

        # SAMMOY2 / Radxa io-helper
        if isinstance(inputs_raw, dict):
            self.last_bill_pulses = int(io.get("nv9_pulses") or 0)
            self.last_coin_pulses = 0

        # Legacy io-helper compatibility
        else:
            inputs = {item["name"]: item for item in inputs_raw}
            bill = inputs.get("bill_pulse", {})
            coin = inputs.get("coin_pulse", {})
            self.last_bill_pulses = int(
                bill.get("rising_count") or bill.get("pulse_count") or 0
            )
            self.last_coin_pulses = int(
                coin.get("rising_count") or coin.get("pulse_count") or 0
            )
        with self.lock:
            self.state["billPulses"] = self.last_bill_pulses
            self.state["coinPulses"] = self.last_coin_pulses

    def _baseline_rfid_events(self) -> None:
        try:
            payload = self._get_rfid_events_sync()
        except Exception:
            return
        with self.lock:
            self.last_rfid_seq = int(payload.get("last_seq") or 0)
            rfid = payload.get("rfid") or {}
            self.state["lastRfidStatus"] = "online" if rfid.get("online") else "offline"

    def _run(self) -> None:
        self._all_off_sync()
        while not self.stop_event.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception as exc:
                with self.lock:
                    self.state["lastError"] = str(exc)
                    self.state["phase"] = "error"
                    self.state["updatedAt"] = now_iso()
                self._all_off_sync()

    def tick(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_tick)
        self.last_tick = now

        io = self._get_io_sync()
        try:
            rfid_payload = self._get_rfid_events_sync(since=self.last_rfid_seq)
        except Exception as exc:
            rfid_payload = {}
            with self.lock:
                self.state["lastRfidStatus"] = str(exc)
        inputs_raw = io.get("inputs", {})

        # SAMMOY2 / Radxa io-helper:
        #   nv9_pulses is the cumulative GPIO11 pulse counter
        #   inputs.total_stop is already normalized using active_low
        if isinstance(inputs_raw, dict):
            bill_pulses = int(io.get("nv9_pulses") or 0)
            physical_coin_pulses = 0
            physical_total_stop_active = bool(
                inputs_raw.get("total_stop", False)
            )

        # Legacy io-helper compatibility
        else:
            inputs = {item["name"]: item for item in inputs_raw}
            bill = inputs.get("bill_pulse", {})
            coin = inputs.get("coin_pulse", {})
            total_stop = inputs.get("total_stop_switch", {})

            bill_pulses = int(
                bill.get("rising_count") or bill.get("pulse_count") or 0
            )
            physical_coin_pulses = int(
                coin.get("rising_count") or coin.get("pulse_count") or 0
            )
            physical_total_stop_active = bool(
                total_stop.get("active", True)
            )

        with self.lock:
            simulated_coin_pulses = int(
                self.simulation.get("coinPulses") or 0
            )
            total_stop_override = self.simulation.get("totalStopActive")

        coin_pulses = physical_coin_pulses + simulated_coin_pulses

        total_stop_active = (
            physical_total_stop_active
            if total_stop_override is None
            else bool(total_stop_override)
        )

        with self.lock:
            self.io_failures = 0
            self.state["lastIoOk"] = True
            self.state["lastError"] = None

            bill_delta = max(0, bill_pulses - self.last_bill_pulses)
            coin_delta = max(0, coin_pulses - self.last_coin_pulses)
            self.last_bill_pulses = bill_pulses
            self.last_coin_pulses = coin_pulses
            self.state["billPulses"] = bill_pulses
            self.state["coinPulses"] = coin_pulses
            if self.state.get("licenseLocked"):
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["activeMode"] = None
                self.state["requestedOutput"] = None
                self.state["phase"] = "license_locked"
                self.state["updatedAt"] = now_iso()
                self._flush_usage_locked()
                self._maybe_cleanup_retention_locked()
                requested_output = None
                skip_runtime = True
            else:
                skip_runtime = False

            if skip_runtime:
                pass
            elif bill_delta:
                amount_sum = bill_delta * int(self.params["billPulseSum"])
                self.state["creditSum"] += amount_sum
                self.state["_creditFloat"] = float(self.state["creditSum"])
                self.state["lastCreditSource"] = "bill_pulse"
                self._record_credit_locked(
                    amount_sum,
                    "bill_pulse",
                    bill_delta,
                    {"rising_count": bill_pulses, "sum_per_pulse": int(self.params["billPulseSum"])},
                )
            if skip_runtime:
                pass
            elif coin_delta:
                amount_sum = coin_delta * int(self.params["coinPulseSum"])
                self.state["creditSum"] += amount_sum
                self.state["_creditFloat"] = float(self.state["creditSum"])
                self.state["lastCreditSource"] = "coin_pulse"
                self._record_credit_locked(
                    amount_sum,
                    "coin_pulse",
                    coin_delta,
                    {
                        "physical_rising_count": physical_coin_pulses,
                        "simulated_pulses": simulated_coin_pulses,
                        "sum_per_pulse": int(self.params["coinPulseSum"]),
                    },
                )

            if skip_runtime:
                requested_output = None
            else:
                self._process_rfid_events_locked(rfid_payload)

            previous_total_stop_active = bool(
                self.state.get("totalStopActive")
            )

            self.state["totalStopActive"] = total_stop_active

            trigger_required = bool(
                self.params.get(
                    "requireTotalStopTrigger",
                    True,
                )
            )

            # True only during the tick in which the WEB-PAUSE
            # trigger-reset interlock is successfully cleared.
            trigger_reset_cleared_this_tick = False

            if not trigger_required:
                # Winter/bypass mode:
                # keep DI3 visible in diagnostics but completely exclude
                # it from program-output permission logic.
                self.state["resumeRequiresTriggerReset"] = False
                self.state["_triggerResetOffFloat"] = 0.0
                self.state["triggerResetConfirmRemaining"] = 0.0
                self.state["_triggerGraceFloat"] = 0.0
                self.state["triggerGraceRemaining"] = 0

            else:
                # WEB-PAUSE restart interlock:
                # a single OFF sample is not enough. The trigger must
                # remain continuously OFF for triggerResetConfirmSeconds.
                if self.state.get("resumeRequiresTriggerReset"):
                    confirm_seconds = max(
                        0.0,
                        float(
                            self.params.get(
                                "triggerResetConfirmSeconds",
                                0.5,
                            )
                        ),
                    )

                    if not total_stop_active:
                        off_time = (
                            float(
                                self.state.get(
                                    "_triggerResetOffFloat",
                                    0.0,
                                )
                            )
                            + elapsed
                        )

                        self.state["_triggerResetOffFloat"] = off_time

                        remaining = max(
                            0.0,
                            confirm_seconds - off_time,
                        )

                        self.state[
                            "triggerResetConfirmRemaining"
                        ] = round(remaining, 2)

                        # Reset confirmation is part of the configured
                        # trigger grace, not additional time.
                        #
                        # Example:
                        #   grace = 1.0 sec
                        #   reset confirm = 0.5 sec
                        # After confirmation only 0.5 sec grace remains.
                        if off_time >= confirm_seconds:
                            configured_grace = max(
                                0.0,
                                float(
                                    self.params.get(
                                        "triggerGraceSeconds",
                                        1,
                                    )
                                ),
                            )

                            grace_remaining = max(
                                0.0,
                                configured_grace - off_time,
                            )

                            self.state[
                                "_triggerGraceFloat"
                            ] = grace_remaining
                            self.state[
                                "triggerGraceRemaining"
                            ] = int(ceil(grace_remaining))

                            self.state[
                                "resumeRequiresTriggerReset"
                            ] = False
                            trigger_reset_cleared_this_tick = True

                            self.state[
                                "_triggerResetOffFloat"
                            ] = 0.0
                            self.state[
                                "triggerResetConfirmRemaining"
                            ] = 0.0

                    else:
                        # Trigger returned ON before confirmation:
                        # restart the OFF confirmation timer.
                        self.state["_triggerResetOffFloat"] = 0.0
                        self.state[
                            "triggerResetConfirmRemaining"
                        ] = confirm_seconds

                else:
                    self.state["_triggerResetOffFloat"] = 0.0
                    self.state["triggerResetConfirmRemaining"] = 0.0

                # Physical ON -> OFF transition starts grace.
                if (
                    previous_total_stop_active
                    and not total_stop_active
                ):
                    grace = max(
                        0.0,
                        float(
                            self.params.get(
                                "triggerGraceSeconds",
                                1,
                            )
                        ),
                    )
                    self.state["_triggerGraceFloat"] = grace
                    self.state["triggerGraceRemaining"] = int(
                        ceil(grace)
                    )

                # Trigger is physically ON.
                if (
                    total_stop_active
                    and not self.state.get(
                        "resumeRequiresTriggerReset"
                    )
                ):
                    self.state["_triggerGraceFloat"] = 0.0
                    self.state["triggerGraceRemaining"] = 0

            selected = self.state.get("selectedMode")
            armed = self.state.get("armedMode")
            credit = int(self.state.get("creditSum") or 0)
            requested_output: str | None = None

            trigger_ready = (
                total_stop_active
                or not trigger_required
            )

            if skip_runtime:
                self.state["requestedOutput"] = None
                self.state["updatedAt"] = now_iso()
                self._apply_output_sync(None)
                return

            if credit <= 0:
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["activeMode"] = None
                self.state["phase"] = "no_credit"
                self.state["pauseState"] = "none"

                self.state["freePauseRemaining"] = 0
                self.state["_pauseBudgetFloat"] = 0.0
                self.state["_pauseBudgetInitialized"] = False

                self.state["triggerGraceRemaining"] = 0
                self.state["_triggerGraceFloat"] = 0.0
                self.state["resumeRequiresTriggerReset"] = False
                self.state["_triggerResetOffFloat"] = 0.0
                self.state["triggerResetConfirmRemaining"] = 0.0

            elif selected == "pause":
                # ----------------------------------------------------
                # WEB PAUSE
                # Highest customer-command priority.
                # Equipment is OFF regardless of trigger state.
                # ----------------------------------------------------
                self.state["activeMode"] = None
                requested_output = None

                self.state["triggerGraceRemaining"] = 0
                self.state["_triggerGraceFloat"] = 0.0

                if (
                    self.state.get("powerRecoveryAvailable")
                    and not armed
                ):
                    self.state["phase"] = "interrupted_resume"
                    self.state["pauseState"] = "none"

                elif armed:
                    self._ensure_pause_budget_locked()

                    free_remaining, paid_elapsed = (
                        self._spend_pause_budget_locked(elapsed)
                    )

                    if free_remaining > 0:
                        self.state["phase"] = "pause_free"
                        self.state["pauseState"] = "free"

                        self._track_usage_locked(
                            "pause",
                            "manual_pause",
                            elapsed,
                            0.0,
                        )

                    else:
                        paid_cfg = self.params.get(
                            "paidPause",
                            {},
                        )

                        if paid_cfg.get("enabled") is False:
                            self.state["phase"] = (
                                "pause_free_exhausted"
                            )
                            self.state["pauseState"] = "none"
                            spent_sum = 0.0
                        else:
                            self.state["phase"] = "pause_paid"
                            self.state["pauseState"] = "paid"

                            spent_sum = (
                                self._charge_paid_pause_locked(
                                    paid_elapsed
                                )
                            )

                        self._track_usage_locked(
                            "pause",
                            "manual_pause",
                            paid_elapsed,
                            spent_sum,
                        )

                else:
                    self.state["phase"] = "idle"
                    self.state["pauseState"] = "none"

            elif (
                armed
                and trigger_required
                and self.state.get(
                    "resumeRequiresTriggerReset"
                )
            ):
                # ----------------------------------------------------
                # User selected a program after WEB PAUSE while the
                # trigger is STILL held.
                #
                # DO must stay OFF until physical trigger OFF is seen.
                # ----------------------------------------------------
                self.state["activeMode"] = None
                requested_output = None

                self._ensure_pause_budget_locked()

                free_remaining, paid_elapsed = (
                    self._spend_pause_budget_locked(elapsed)
                )

                if free_remaining > 0:
                    self.state["phase"] = (
                        "trigger_reset_pause_free"
                    )
                    self.state["pauseState"] = "free"

                    self._track_usage_locked(
                        "pause",
                        "manual_pause",
                        elapsed,
                        0.0,
                    )

                else:
                    paid_cfg = self.params.get(
                        "paidPause",
                        {},
                    )

                    if paid_cfg.get("enabled") is False:
                        self.state["phase"] = (
                            "trigger_reset_required"
                        )
                        self.state["pauseState"] = "none"
                        spent_sum = 0.0
                    else:
                        self.state["phase"] = (
                            "trigger_reset_pause_paid"
                        )
                        self.state["pauseState"] = "paid"

                        spent_sum = (
                            self._charge_paid_pause_locked(
                                paid_elapsed
                            )
                        )

                    self._track_usage_locked(
                        "pause",
                        "manual_pause",
                        paid_elapsed,
                        spent_sum,
                    )

            elif armed and not trigger_ready:
                # ----------------------------------------------------
                # Physical trigger released.
                #
                # 1) trigger grace
                # 2) shared free pause
                # 3) paid pause
                # ----------------------------------------------------
                self.state["activeMode"] = None
                requested_output = None

                if trigger_reset_cleared_this_tick:
                    # The current elapsed interval was already included
                    # in the stable-OFF confirmation calculation above.
                    # Do not consume it again here.
                    grace_remaining = int(
                        self.state.get(
                            "triggerGraceRemaining",
                            0,
                        )
                    )
                    pause_elapsed = 0.0
                else:
                    grace_remaining, pause_elapsed = (
                        self._spend_trigger_grace_locked(
                            elapsed
                        )
                    )

                if grace_remaining > 0:
                    self.state["phase"] = "trigger_grace"
                    self.state["pauseState"] = "none"

                else:
                    self._ensure_pause_budget_locked()

                    free_remaining, paid_elapsed = (
                        self._spend_pause_budget_locked(
                            pause_elapsed
                        )
                    )

                    if free_remaining > 0:
                        self.state["phase"] = "pause_free"
                        self.state["pauseState"] = "free"

                        self._track_usage_locked(
                            "pause",
                            "total_stop_wait",
                            pause_elapsed,
                            0.0,
                        )

                    else:
                        paid_cfg = self.params.get(
                            "paidPause",
                            {},
                        )

                        if paid_cfg.get("enabled") is False:
                            self.state["phase"] = (
                                "pause_free_exhausted"
                            )
                            self.state["pauseState"] = "none"
                            spent_sum = 0.0
                        else:
                            self.state["phase"] = "pause_paid"
                            self.state["pauseState"] = "paid"

                            spent_sum = (
                                self._charge_paid_pause_locked(
                                    paid_elapsed
                                )
                            )

                        self._track_usage_locked(
                            "pause",
                            "total_stop_wait",
                            paid_elapsed,
                            spent_sum,
                        )

            elif armed:
                # ----------------------------------------------------
                # Normal active program.
                # ----------------------------------------------------
                if armed not in MODE_OUTPUTS:
                    self.state["phase"] = "unsupported_mode"
                    self.state["activeMode"] = None
                    self.state["pauseState"] = "none"

                else:
                    self.state["phase"] = "active"
                    self.state["activeMode"] = armed
                    self.state["pauseState"] = "none"

                    self.state["triggerGraceRemaining"] = 0
                    self.state["_triggerGraceFloat"] = 0.0

                    requested_output = armed

                    spent_sum = self._charge_active_locked(
                        armed,
                        elapsed,
                    )

                    self._track_usage_locked(
                        armed,
                        "active",
                        elapsed,
                        spent_sum,
                    )

            else:
                self.state["phase"] = "idle"
                self.state["activeMode"] = None
                self.state["pauseState"] = "none"

            if int(self.state["creditSum"]) <= 0:
                closing_session_id = self.active_session_id
                self.state["creditSum"] = 0
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["phase"] = "no_credit"
                self.state["activeMode"] = None
                self.state["freePauseRemaining"] = 0
                self.state["_pauseBudgetFloat"] = 0.0
                self.state["_pauseBudgetInitialized"] = False
                self.state["pauseState"] = "none"

                self.state["triggerGraceRemaining"] = 0
                self.state["_triggerGraceFloat"] = 0.0
                self.state["resumeRequiresTriggerReset"] = False
                self.state["_triggerResetOffFloat"] = 0.0
                self.state["triggerResetConfirmRemaining"] = 0.0

                requested_output = None
                if closing_session_id:
                    self._close_session_locked("credit_empty")

            self.state["requestedOutput"] = requested_output
            self.state["updatedAt"] = now_iso()
            if time.monotonic() - self.last_ledger_flush >= LEDGER_FLUSH_SECONDS:
                self._flush_usage_locked()
                self._heartbeat_session_locked()
                self.last_ledger_flush = time.monotonic()
            self._maybe_cleanup_retention_locked()

        self._apply_output_sync(requested_output)

    def _charge_active_locked(self, mode: str, elapsed: float) -> float:
        tariff = self.params["tariffs"].get(mode, {})
        amount_sum = int(tariff.get("amountSum") or 0)
        duration_seconds = int(tariff.get("durationSeconds") or 0)
        if amount_sum <= 0 or duration_seconds <= 0:
            return 0.0
        current = float(self.state.get("_creditFloat", self.state.get("creditSum", 0)))
        next_credit = max(0.0, current - (amount_sum / duration_seconds) * elapsed)
        spent_sum = max(0.0, current - next_credit)
        self.state["_creditFloat"] = next_credit
        # Keep the last fractional sum visible until it is actually consumed.
        # Flooring here used to close the session early and lose the final
        # fraction from both service time and the accounting ledger.
        self.state["creditSum"] = int(ceil(next_credit))
        return spent_sum

    def _source_for_session(self, source: str) -> str:
        if source in {"bill_pulse", "coin_pulse"}:
            return "cash"
        if source in {"click", "card", "vip", "admin"}:
            return source
        if source == "manual":
            return "admin"
        return "unknown"

    def _provider_for_payment(self, source: str) -> str:
        if source in {"bill_pulse", "coin_pulse"}:
            return "cash"
        if source in {"click", "card", "vip", "admin", "manual"}:
            return source
        return "manual"

    def _vip_grant_amount_sum(self, grant_seconds: int) -> int:
        water = self.params["tariffs"].get("water", {})
        amount_sum = int(water.get("amountSum") or 0)
        duration_seconds = int(water.get("durationSeconds") or 0)
        if amount_sum <= 0 or duration_seconds <= 0 or grant_seconds <= 0:
            return 0
        return int(round((amount_sum / duration_seconds) * grant_seconds))

    def _process_rfid_events_locked(self, payload: dict[str, Any]) -> None:
        if not payload:
            return
        self.last_rfid_seq = int(payload.get("last_seq") or self.last_rfid_seq)
        rfid = payload.get("rfid") or {}
        if rfid.get("last_error"):
            self.state["lastRfidStatus"] = str(rfid["last_error"])
        elif rfid.get("online"):
            self.state["lastRfidStatus"] = "online"
        else:
            self.state["lastRfidStatus"] = "offline"

        for event in payload.get("events") or []:
            uid = str(event.get("uid") or "").strip().upper()
            seq = int(event.get("seq") or 0)
            if not uid:
                continue
            self.state["lastRfidUid"] = uid
            self.last_rfid_seq = max(self.last_rfid_seq, seq)
            try:
                self._apply_rfid_card_locked(uid, event)
            except Exception as exc:
                self.state["lastRfidStatus"] = f"rfid_error: {exc}"

    def _apply_rfid_card_locked(self, uid: str, event: dict[str, Any]) -> None:
        with db() as conn:
            card = conn.execute(
                """
                SELECT c.uid, c.card_type, c.status, c.enabled, c.balance_sum, c.vip_profile_id,
                       p.code AS vip_code, p.name AS vip_name, p.enabled AS vip_enabled,
                       p.grant_seconds, p.max_uses_per_day
                FROM rfid_cards c
                LEFT JOIN vip_profiles p ON p.id = c.vip_profile_id
                WHERE c.uid = %s
                """,
                (uid,),
            ).fetchone()
            if not card:
                current_credit = int(self.state.get("creditSum") or 0)
                conn.execute(
                    """
                    INSERT INTO rfid_cards (uid, card_type, status, enabled, balance_sum, last_seen_at, updated_at)
                    VALUES (%s, 'customer', 'active', true, 0, now(), now())
                    ON CONFLICT (uid) DO UPDATE
                    SET last_seen_at = now(), updated_at = now()
                    """,
                    (uid,),
                )
                conn.execute(
                    """
                    INSERT INTO system_events (level, event_type, source, message, context)
                    VALUES ('info', 'rfid_customer_card_seen', 'wash-engine', %s, %s)
                    """,
                    (f"Customer RFID card {uid} seen", Jsonb({"uid": uid, "event": event})),
                )
                conn.commit()
                if current_credit > 0:
                    if self.active_session_source == "vip":
                        self._burn_remaining_locked("vip_remaining_burned")
                        self.state["lastRfidStatus"] = "vip_remaining_burned"
                        return
                    self._save_remaining_to_customer_card_locked(uid, event)
                    self.state["lastRfidStatus"] = "customer_balance_saved"
                    return
                self.state["lastRfidStatus"] = "customer_card_seen"
                return

            conn.execute(
                "UPDATE rfid_cards SET last_seen_at = now(), updated_at = now() WHERE uid = %s",
                (uid,),
            )

            if not card["enabled"] or card["status"] != "active":
                conn.execute(
                    """
                    INSERT INTO system_events (level, event_type, source, message, context)
                    VALUES ('warning', 'rfid_card_rejected', 'wash-engine', %s, %s)
                    """,
                    (f"RFID card {uid} rejected", Jsonb({"uid": uid, "status": card["status"], "enabled": card["enabled"]})),
                )
                conn.commit()
                self.state["lastRfidStatus"] = "card_rejected"
                return

            if card["card_type"] == "customer":
                balance_sum = int(card["balance_sum"] or 0)
                current_credit = int(self.state.get("creditSum") or 0)
                conn.commit()
                if current_credit > 0:
                    if self.active_session_source == "vip":
                        self._burn_remaining_locked("vip_remaining_burned")
                        self.state["lastRfidStatus"] = "vip_remaining_burned"
                        return
                    self._save_remaining_to_customer_card_locked(uid, event)
                    self.state["lastRfidStatus"] = "customer_balance_saved"
                    return
                if balance_sum > 0:
                    self._use_customer_balance_locked(uid, balance_sum, event)
                    self.state["lastRfidStatus"] = "customer_balance_used"
                    return
                self.state["lastRfidStatus"] = "customer_card_seen"
                return

            if card["card_type"] != "vip":
                conn.commit()
                self.state["lastRfidStatus"] = f"{card['card_type']}_card_seen"
                return

            if not card["vip_profile_id"] or not card["vip_enabled"]:
                conn.execute(
                    """
                    INSERT INTO system_events (level, event_type, source, message, context)
                    VALUES ('warning', 'rfid_vip_rejected', 'wash-engine', %s, %s)
                    """,
                    (f"VIP RFID card {uid} has no enabled profile", Jsonb({"uid": uid, "vip_profile_id": card["vip_profile_id"]})),
                )
                conn.commit()
                self.state["lastRfidStatus"] = "vip_profile_disabled"
                return

            current_credit = int(self.state.get("creditSum") or 0)
            if self.active_session_id and current_credit > 0:
                if self.active_session_card_uid == uid:
                    conn.commit()
                    self._burn_remaining_locked("vip_card_toggled_off")
                    self.state["lastRfidStatus"] = "vip_session_closed"
                    return
                conn.execute(
                    """
                    INSERT INTO system_events (level, event_type, source, message, context, wash_session_id)
                    VALUES ('warning', 'rfid_vip_session_active', 'wash-engine', %s, %s, %s)
                    """,
                    (
                        f"VIP RFID card {uid} ignored while another session is active",
                        Jsonb(
                            {
                                "uid": uid,
                                "active_card_uid": self.active_session_card_uid,
                                "active_session_source": self.active_session_source,
                                "credit_sum": current_credit,
                            }
                        ),
                        self.active_session_id,
                    ),
                )
                conn.commit()
                self.state["lastRfidStatus"] = "vip_session_active"
                return

            max_uses = card["max_uses_per_day"]
            if max_uses:
                used_today = conn.execute(
                    """
                    SELECT count(*) AS count
                    FROM rfid_card_ledger
                    WHERE card_uid = %s
                      AND reason = 'vip_grant'
                      AND created_at >= date_trunc('day', now())
                    """,
                    (uid,),
                ).fetchone()["count"]
                if int(used_today) >= int(max_uses):
                    conn.execute(
                        """
                        INSERT INTO system_events (level, event_type, source, message, context)
                        VALUES ('warning', 'rfid_vip_daily_limit', 'wash-engine', %s, %s)
                        """,
                        (f"VIP RFID card {uid} daily limit reached", Jsonb({"uid": uid, "max_uses_per_day": max_uses})),
                    )
                    conn.commit()
                    self.state["lastRfidStatus"] = "vip_daily_limit"
                    return

            grant_seconds = int(card["grant_seconds"] or 0)
            amount_sum = self._vip_grant_amount_sum(grant_seconds)
            if grant_seconds <= 0 or amount_sum <= 0:
                conn.commit()
                self.state["lastRfidStatus"] = "vip_empty_grant"
                return
            conn.commit()

        self.state["creditSum"] = max(0, int(self.state["creditSum"]) + amount_sum)
        self.state["_creditFloat"] = float(self.state["creditSum"])
        self.state["lastCreditSource"] = "vip"
        self._record_credit_locked(
            amount_sum,
            "vip",
            None,
            {"uid": uid, "grant_seconds": grant_seconds, "rfid_event": event, "conversion": "water_tariff"},
        )
        session_id = self.active_session_id
        self.active_session_card_uid = uid
        self.state["activeSessionCardUid"] = uid
        with db() as conn:
            conn.execute(
                "UPDATE wash_sessions SET card_uid = %s, source = CASE WHEN source = 'unknown' THEN 'vip' ELSE source END WHERE id = %s",
                (uid, session_id),
            )
            conn.execute(
                """
                INSERT INTO rfid_card_ledger
                  (card_uid, wash_session_id, direction, reason, amount_sum, duration_seconds, balance_after_sum, raw_payload)
                VALUES (%s, %s, 'grant', 'vip_grant', %s, %s, NULL, %s)
                """,
                (
                    uid,
                    session_id,
                    amount_sum,
                    grant_seconds,
                    Jsonb({"rfid_event": event, "conversion": "water_tariff"}),
                ),
            )
            conn.execute(
                """
                INSERT INTO system_events (level, event_type, source, message, context, wash_session_id)
                VALUES ('info', 'rfid_vip_granted', 'wash-engine', %s, %s, %s)
                """,
                (
                    f"VIP RFID card {uid} granted {grant_seconds} seconds",
                    Jsonb({"uid": uid, "amount_sum": amount_sum, "duration_seconds": grant_seconds}),
                    session_id,
                ),
            )
            conn.commit()
        self.state["lastRfidStatus"] = "vip_granted"

    def _burn_remaining_locked(self, reason: str) -> None:
        if int(self.state.get("creditSum") or 0) <= 0:
            return
        session_id = self.active_session_id
        self.state["creditSum"] = 0
        self.state["_creditFloat"] = 0.0
        self.state["selectedMode"] = "pause"
        self.state["armedMode"] = None
        self.state["activeMode"] = None
        self.state["requestedOutput"] = None
        self.state["freePauseRemaining"] = 0
        self.state["_pauseBudgetFloat"] = 0.0
        if session_id:
            self._close_session_locked(reason)

    def _save_remaining_to_customer_card_locked(self, uid: str, event: dict[str, Any]) -> None:
        amount_sum = int(self.state.get("creditSum") or 0)
        if amount_sum <= 0:
            return
        session_id = self.active_session_id
        if not session_id:
            session_id = self._ensure_session_locked("card")
        self._flush_usage_locked(close=True, settle_spent=True)
        with db() as conn:
            row = conn.execute(
                """
                UPDATE rfid_cards
                SET balance_sum = balance_sum + %s,
                    last_seen_at = now(),
                    updated_at = now()
                WHERE uid = %s
                RETURNING balance_sum
                """,
                (amount_sum, uid),
            ).fetchone()
            balance_after = int(row["balance_sum"] if row else amount_sum)
            conn.execute(
                """
                INSERT INTO rfid_card_ledger
                  (card_uid, wash_session_id, direction, reason, amount_sum, duration_seconds, balance_after_sum, raw_payload)
                VALUES (%s, %s, 'credit', 'save_remaining', %s, 0, %s, %s)
                """,
                (uid, session_id, amount_sum, balance_after, Jsonb({"rfid_event": event})),
            )
            conn.execute(
                """
                INSERT INTO system_events (level, event_type, source, message, context, wash_session_id)
                VALUES ('info', 'rfid_customer_balance_saved', 'wash-engine', %s, %s, %s)
                """,
                (
                    f"Customer RFID card {uid} saved {amount_sum} sum",
                    Jsonb({"uid": uid, "amount_sum": amount_sum, "balance_after_sum": balance_after}),
                    session_id,
                ),
            )
            conn.commit()
        self.state["creditSum"] = 0
        self.state["_creditFloat"] = 0.0
        self.state["selectedMode"] = "pause"
        self.state["armedMode"] = None
        self.state["activeMode"] = None
        self.state["requestedOutput"] = None
        self.state["freePauseRemaining"] = 0
        self.state["_pauseBudgetFloat"] = 0.0
        self._close_session_locked("saved_to_customer_card")

    def _use_customer_balance_locked(self, uid: str, amount_sum: int, event: dict[str, Any]) -> None:
        if amount_sum <= 0:
            return
        with db() as conn:
            row = conn.execute(
                """
                UPDATE rfid_cards
                SET balance_sum = 0,
                    last_seen_at = now(),
                    updated_at = now()
                WHERE uid = %s
                  AND balance_sum = %s
                RETURNING balance_sum
                """,
                (uid, amount_sum),
            ).fetchone()
            conn.commit()
        if row is None:
            self.state["lastRfidStatus"] = "customer_balance_changed"
            return

        self.state["creditSum"] = max(0, int(self.state["creditSum"]) + amount_sum)
        self.state["_creditFloat"] = float(self.state["creditSum"])
        self.state["lastCreditSource"] = "card"
        self._record_credit_locked(amount_sum, "card", None, {"uid": uid, "rfid_event": event})
        session_id = self.active_session_id
        with db() as conn:
            conn.execute(
                "UPDATE wash_sessions SET card_uid = %s, source = CASE WHEN source = 'unknown' THEN 'card' ELSE source END WHERE id = %s",
                (uid, session_id),
            )
            conn.execute(
                """
                INSERT INTO rfid_card_ledger
                  (card_uid, wash_session_id, direction, reason, amount_sum, duration_seconds, balance_after_sum, raw_payload)
                VALUES (%s, %s, 'debit', 'use_balance', %s, 0, 0, %s)
                """,
                (uid, session_id, amount_sum, Jsonb({"rfid_event": event})),
            )
            conn.execute(
                """
                INSERT INTO system_events (level, event_type, source, message, context, wash_session_id)
                VALUES ('info', 'rfid_customer_balance_used', 'wash-engine', %s, %s, %s)
                """,
                (
                    f"Customer RFID card {uid} used {amount_sum} sum",
                    Jsonb({"uid": uid, "amount_sum": amount_sum}),
                    session_id,
                ),
            )
            conn.commit()

    def _ensure_session_locked(self, source: str) -> int:
        if self.active_session_id:
            session_source = self._source_for_session(source)
            if self.active_session_source != session_source and self.active_session_source != "mixed":
                self.active_session_source = "mixed"
                with db() as conn:
                    conn.execute(
                        "UPDATE wash_sessions SET source = 'mixed', status = 'running' WHERE id = %s",
                        (self.active_session_id,),
                    )
                    conn.commit()
            return self.active_session_id

        session_source = self._source_for_session(source)
        initial_credit = int(self.state.get("creditSum") or 0)
        with db() as conn:
            row = conn.execute(
                """
                INSERT INTO wash_sessions
                  (status, source, initial_credit_sum, metadata)
                VALUES ('running', %s, %s, %s)
                RETURNING id
                """,
                (session_source, initial_credit, Jsonb({"created_by": "wash-runtime", "credit_source": source})),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO system_events (level, event_type, source, message, context, wash_session_id)
                VALUES ('info', 'wash_session_started', 'wash-engine', %s, %s, %s)
                """,
                (
                    f"Wash session {row['id']} started",
                    Jsonb({"credit_source": source, "initial_credit_sum": initial_credit}),
                    row["id"],
                ),
            )
            conn.commit()
        self.active_session_id = int(row["id"])
        self.active_session_source = session_source
        self.active_session_initial_credit = initial_credit
        self.state["activeSessionId"] = self.active_session_id
        return self.active_session_id

    def _record_credit_locked(
        self,
        amount_sum: int,
        source: str,
        pulse_count: int | None,
        raw_payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> None:
        if amount_sum <= 0:
            return
        session_id = self._ensure_session_locked(source)
        provider = self._provider_for_payment(source)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO payments
                  (wash_session_id, provider, status, amount_sum, idempotency_key, raw_payload, credited_at)
                VALUES (%s, %s, 'credited', %s, %s, %s, now())
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    session_id,
                    provider,
                    amount_sum,
                    idempotency_key or f"{source}:{session_id}:{time.monotonic_ns()}",
                    Jsonb(raw_payload),
                ),
            )
            if source in {"bill_pulse", "coin_pulse"} and pulse_count:
                conn.execute(
                    """
                    INSERT INTO cash_events
                      (wash_session_id, source_input, pulse_count, amount_sum, sum_per_pulse, raw_payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        source,
                        pulse_count,
                        amount_sum,
                        int(amount_sum / pulse_count) if pulse_count else amount_sum,
                        Jsonb(raw_payload),
                    ),
                )
            conn.execute(
                """
                UPDATE wash_sessions
                SET paid_sum = COALESCE(paid_sum, 0) + %s,
                    final_credit_sum = %s,
                    status = 'running',
                    runtime_seen_at = now()
                WHERE id = %s
                """,
                (amount_sum, int(self.state.get("creditSum") or 0), session_id),
            )
            conn.commit()

    def _track_usage_locked(self, mode: str, usage_kind: str, elapsed: float, spent_sum: float) -> None:
        if elapsed <= 0 and spent_sum <= 0:
            return
        session_id = self.active_session_id
        if not session_id:
            return
        if self.active_usage_mode != mode:
            self._flush_usage_locked(close=True)
            with db() as conn:
                row = conn.execute(
                    """
                    INSERT INTO mode_usage (wash_session_id, mode, metadata)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (session_id, mode, Jsonb({"started_phase": self.state.get("phase")})),
                ).fetchone()
                conn.commit()
            self.active_usage_id = int(row["id"])
            self.active_usage_mode = mode
            self.pending_usage = {"duration_ms": 0.0, "spent_sum": 0.0, "pause_ms": 0.0, "total_stop_wait_ms": 0.0}

        elapsed_ms = elapsed * 1000.0
        if usage_kind == "active":
            self.pending_usage["duration_ms"] += elapsed_ms
        elif usage_kind == "manual_pause":
            self.pending_usage["pause_ms"] += elapsed_ms
        elif usage_kind == "total_stop_wait":
            self.pending_usage["total_stop_wait_ms"] += elapsed_ms
        self.pending_usage["spent_sum"] += spent_sum

    def _take_ledger_spent_locked(self, settle: bool = False) -> int:
        pending = float(self.pending_usage.get("spent_sum") or 0.0)
        total = max(0.0, self.ledger_spent_carry + pending)
        spent_sum = int(round(total)) if settle else int(total)
        self.ledger_spent_carry = 0.0 if settle else total - spent_sum
        return spent_sum

    def _flush_usage_locked(self, close: bool = False, settle_spent: bool = False) -> None:
        if not self.active_usage_id:
            return
        duration_ms = int(self.pending_usage.get("duration_ms") or 0)
        spent_sum = self._take_ledger_spent_locked(settle=settle_spent)
        pause_ms = int(self.pending_usage.get("pause_ms") or 0)
        total_stop_wait_ms = int(self.pending_usage.get("total_stop_wait_ms") or 0)
        if duration_ms <= 0 and spent_sum <= 0 and pause_ms <= 0 and total_stop_wait_ms <= 0 and not close:
            return
        with db() as conn:
            conn.execute(
                """
                UPDATE mode_usage
                SET duration_ms = duration_ms + %s,
                    spent_sum = spent_sum + %s,
                    pause_ms = pause_ms + %s,
                    total_stop_wait_ms = total_stop_wait_ms + %s,
                    ended_at = CASE WHEN %s THEN now() ELSE ended_at END
                WHERE id = %s
                """,
                (duration_ms, spent_sum, pause_ms, total_stop_wait_ms, close, self.active_usage_id),
            )
            if self.active_session_id and spent_sum > 0:
                conn.execute(
                    """
                    UPDATE wash_sessions
                    SET total_spent_sum = total_spent_sum + %s,
                        final_credit_sum = %s,
                        status = 'running',
                        runtime_seen_at = now()
                    WHERE id = %s
                    """,
                    (spent_sum, int(self.state.get("creditSum") or 0), self.active_session_id),
                )
            conn.commit()
        self.pending_usage = {"duration_ms": 0.0, "spent_sum": 0.0, "pause_ms": 0.0, "total_stop_wait_ms": 0.0}
        if close:
            self.active_usage_id = None
            self.active_usage_mode = None

    def _close_session_locked(self, reason: str) -> None:
        if not self.active_session_id:
            return
        session_id = self.active_session_id
        self._flush_usage_locked(close=True, settle_spent=True)
        with db() as conn:
            conn.execute(
                """
                UPDATE wash_sessions
                SET status = 'ended',
                    finished_at = now(),
                    ended_at = now(),
                    final_credit_sum = %s,
                    close_reason = %s
                WHERE id = %s
                """,
                (int(self.state.get("creditSum") or 0), reason, session_id),
            )
            conn.execute(
                """
                INSERT INTO system_events (level, event_type, source, message, context, wash_session_id)
                VALUES ('info', 'wash_session_ended', 'wash-engine', %s, %s, %s)
                """,
                (
                    f"Wash session {session_id} ended",
                    Jsonb({"reason": reason, "final_credit_sum": int(self.state.get("creditSum") or 0)}),
                    session_id,
                ),
            )
            conn.commit()
        self.active_session_id = None
        self.active_session_source = "unknown"
        self.active_session_card_uid = None
        self.active_session_initial_credit = 0
        self.ledger_spent_carry = 0.0
        self.state["activeSessionId"] = None
        self.state["activeSessionCardUid"] = None

    def _heartbeat_session_locked(self) -> None:
        """
        Persist the latest known customer balance and a timestamp.

        This allows the runtime to distinguish a short power outage
        from an abandoned session after reboot.
        """
        if not self.active_session_id:
            return

        with db() as conn:
            conn.execute(
                """
                UPDATE wash_sessions
                SET final_credit_sum = %s,
                    runtime_seen_at = now(),
                    status = 'running',
                    metadata = metadata || jsonb_build_object(
                        'pause_budget_initialized', %s,
                        'free_pause_remaining', %s
                    )
                WHERE id = %s
                """,
                (
                    int(self.state.get("creditSum") or 0),
                    bool(
                        self.state.get(
                            "_pauseBudgetInitialized",
                            False,
                        )
                    ),
                    max(
                        0.0,
                        float(
                            self.state.get(
                                "_pauseBudgetFloat",
                                0.0,
                            )
                        ),
                    ),
                    self.active_session_id,
                ),
            )
            conn.commit()


    def _maybe_cleanup_retention_locked(self) -> None:
        now = time.monotonic()
        if now - self.last_retention_cleanup < 24 * 60 * 60:
            return
        self.last_retention_cleanup = now
        self._cleanup_retention_sync()

    def _recover_interrupted_sessions_sync(self) -> int:
        """
        Power recovery policy:

        - outage <= powerRecoverySeconds:
            restore ONE newest session with remaining credit;
            restore money/session only;
            NEVER restore outputs or active mode.

        - outage > powerRecoverySeconds:
            close old session;
            preserve remaining credit in recovery_credits.

        Older orphaned open sessions are always closed.
        """
        recovery_seconds = int(
            self.params.get("powerRecoverySeconds") or 600
        )

        recovered_count = 0

        with db() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    source,
                    card_uid,
                    initial_credit_sum,
                    paid_sum,
                    total_spent_sum,
                    final_credit_sum,
                    metadata,
                    started_at,
                    runtime_seen_at,
                    EXTRACT(
                        EPOCH FROM (
                            now() - COALESCE(runtime_seen_at, started_at)
                        )
                    ) AS downtime_seconds
                FROM wash_sessions
                WHERE status IN ('started', 'running', 'open')
                ORDER BY
                    COALESCE(runtime_seen_at, started_at) DESC,
                    id DESC
                """
            ).fetchall()

            recover_candidate = None

            for row in rows:
                session_id = int(row["id"])
                downtime_seconds = max(
                    0,
                    int(float(row["downtime_seconds"] or 0)),
                )

                remaining_credit = max(
                    0,
                    int(row["final_credit_sum"] or 0),
                )

                can_recover = (
                    recover_candidate is None
                    and remaining_credit > 0
                    and downtime_seconds <= recovery_seconds
                )

                if can_recover:
                    recover_candidate = row

                    # A program that was running before the power loss
                    # must never be resumed automatically.
                    conn.execute(
                        """
                        UPDATE mode_usage
                        SET ended_at = COALESCE(ended_at, now()),
                            metadata = metadata || jsonb_build_object(
                                'close_reason', 'power_interrupted_resume'
                            )
                        WHERE wash_session_id = %s
                          AND ended_at IS NULL
                        """,
                        (session_id,),
                    )

                    conn.execute(
                        """
                        UPDATE wash_sessions
                        SET status = 'running',
                            finished_at = NULL,
                            ended_at = NULL,
                            close_reason = '',
                            runtime_seen_at = now(),
                            metadata = metadata || jsonb_build_object(
                                'power_recovered', true,
                                'power_recovered_at', now(),
                                'power_downtime_seconds', %s,
                                'power_recovery_limit_seconds', %s
                            )
                        WHERE id = %s
                        """,
                        (
                            downtime_seconds,
                            recovery_seconds,
                            session_id,
                        ),
                    )

                    conn.execute(
                        """
                        INSERT INTO system_events
                          (
                            level,
                            event_type,
                            source,
                            message,
                            context,
                            wash_session_id
                          )
                        VALUES (
                            'warning',
                            'wash_session_power_recovered',
                            'wash-engine',
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            f"Wash session {session_id} restored after power loss",
                            Jsonb(
                                {
                                    "remaining_credit_sum": remaining_credit,
                                    "downtime_seconds": downtime_seconds,
                                    "recovery_limit_seconds": recovery_seconds,
                                }
                            ),
                            session_id,
                        ),
                    )

                    recovered_count += 1
                    continue

                # Timeout or stale/orphaned session:
                # close it but DO NOT destroy remaining money.
                conn.execute(
                    """
                    UPDATE mode_usage
                    SET ended_at = COALESCE(ended_at, now()),
                        metadata = metadata || jsonb_build_object(
                            'close_reason',
                            'power_interruption_timeout'
                        )
                    WHERE wash_session_id = %s
                      AND ended_at IS NULL
                    """,
                    (session_id,),
                )

                conn.execute(
                    """
                    UPDATE wash_sessions
                    SET status = 'ended',
                        finished_at = COALESCE(finished_at, now()),
                        ended_at = COALESCE(ended_at, now()),
                        close_reason = 'power_interruption_timeout',
                        final_credit_sum = %s,
                        metadata = metadata || jsonb_build_object(
                            'power_recovery_expired', true,
                            'power_recovery_expired_at', now(),
                            'power_downtime_seconds', %s,
                            'power_recovery_limit_seconds', %s
                        )
                    WHERE id = %s
                    """,
                    (
                        remaining_credit,
                        downtime_seconds,
                        recovery_seconds,
                        session_id,
                    ),
                )

                if remaining_credit > 0:
                    conn.execute(
                        """
                        INSERT INTO recovery_credits
                          (
                            wash_session_id,
                            amount_sum,
                            reason,
                            status,
                            metadata
                          )
                        VALUES (
                            %s,
                            %s,
                            'power_interruption_timeout',
                            'unclaimed',
                            %s
                        )
                        ON CONFLICT (wash_session_id) DO NOTHING
                        """,
                        (
                            session_id,
                            remaining_credit,
                            Jsonb(
                                {
                                    "downtime_seconds": downtime_seconds,
                                    "recovery_limit_seconds": recovery_seconds,
                                }
                            ),
                        ),
                    )

                conn.execute(
                    """
                    INSERT INTO system_events
                      (
                        level,
                        event_type,
                        source,
                        message,
                        context,
                        wash_session_id
                      )
                    VALUES (
                        'warning',
                        'wash_session_power_timeout',
                        'wash-engine',
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        f"Wash session {session_id} expired after power loss",
                        Jsonb(
                            {
                                "remaining_credit_sum": remaining_credit,
                                "downtime_seconds": downtime_seconds,
                                "recovery_limit_seconds": recovery_seconds,
                            }
                        ),
                        session_id,
                    ),
                )

            conn.commit()

        if recover_candidate is not None:
            remaining_credit = max(
                0,
                int(recover_candidate["final_credit_sum"] or 0),
            )

            downtime_seconds = max(
                0,
                int(float(recover_candidate["downtime_seconds"] or 0)),
            )

            recovery_metadata = (
                recover_candidate.get("metadata") or {}
            )

            pause_budget_key_present = (
                "pause_budget_initialized"
                in recovery_metadata
            )

            recovered_pause_initialized = bool(
                recovery_metadata.get(
                    "pause_budget_initialized",
                    False,
                )
            )

            recovered_pause_remaining = max(
                0.0,
                float(
                    recovery_metadata.get(
                        "free_pause_remaining",
                        0.0,
                    )
                    or 0.0
                ),
            )

            # Never restore more free pause than currently configured.
            recovered_pause_remaining = min(
                recovered_pause_remaining,
                max(
                    0.0,
                    float(
                        self.params.get(
                            "freePauseSeconds",
                            60,
                        )
                    ),
                ),
            )

            # Legacy session without persistence data:
            # fail safe -- do not grant a fresh 60 seconds after reboot.
            if not pause_budget_key_present:
                recovered_pause_initialized = True
                recovered_pause_remaining = 0.0

            with self.lock:
                self.active_session_id = int(
                    recover_candidate["id"]
                )

                self.active_session_source = (
                    recover_candidate["source"] or "unknown"
                )

                self.active_session_card_uid = (
                    recover_candidate["card_uid"]
                )

                self.active_session_initial_credit = int(
                    recover_candidate["initial_credit_sum"] or 0
                )

                self.active_usage_id = None
                self.active_usage_mode = None

                self.state["creditSum"] = remaining_credit
                self.state["_creditFloat"] = float(remaining_credit)

                # SAFETY:
                # customer must explicitly choose/continue after reboot.
                self.state["selectedMode"] = "pause"
                self.state["armedMode"] = None
                self.state["activeMode"] = None
                self.state["requestedOutput"] = None

                self.state["activeSessionId"] = (
                    self.active_session_id
                )
                self.state["activeSessionCardUid"] = (
                    self.active_session_card_uid
                )

                self.state["phase"] = "interrupted_resume"

                self.state["_pauseBudgetInitialized"] = (
                    recovered_pause_initialized
                )
                self.state["_pauseBudgetFloat"] = (
                    recovered_pause_remaining
                )
                self.state["freePauseRemaining"] = int(
                    ceil(recovered_pause_remaining)
                )

                self.state["powerRecoveryAvailable"] = True
                self.state["powerRecoveryDowntimeSeconds"] = (
                    downtime_seconds
                )
                self.state["powerRecoveryLimitSeconds"] = (
                    recovery_seconds
                )

                self.state["updatedAt"] = now_iso()

        return recovered_count


    def _cleanup_retention_sync(self) -> None:
        try:
            with db() as conn:
                conn.execute("DELETE FROM auth_revoked_tokens WHERE expires_at < now()")
                conn.execute("DELETE FROM settings_history WHERE created_at < now() - interval '90 days'")
                conn.execute("DELETE FROM mode_usage WHERE started_at < now() - interval '90 days'")
                conn.execute("DELETE FROM cash_events WHERE created_at < now() - interval '90 days'")
                conn.execute("DELETE FROM payments WHERE created_at < now() - interval '90 days'")
                conn.execute("DELETE FROM rfid_card_ledger WHERE created_at < now() - interval '90 days'")
                conn.execute("DELETE FROM click_payment_intents WHERE created_at < now() - interval '90 days'")
                conn.execute("DELETE FROM wash_sessions WHERE started_at < now() - interval '90 days'")
                conn.execute("DELETE FROM system_events WHERE created_at < now() - interval '90 days'")
                conn.commit()
        except Exception:
            pass

    def _ensure_pause_budget_locked(self) -> None:
        """
        Initialize the free-pause budget once for a funded session.

        Program changes and repeated PAUSE presses must never replenish it.
        """
        if int(self.state.get("creditSum") or 0) <= 0:
            return

        if self.state.get("_pauseBudgetInitialized"):
            return

        seconds = max(
            0.0,
            float(
                self.params.get(
                    "freePauseSeconds",
                    FREE_PAUSE_SECONDS,
                )
            ),
        )

        self.state["_pauseBudgetFloat"] = seconds
        self.state["freePauseRemaining"] = int(ceil(seconds))
        self.state["_pauseBudgetInitialized"] = True


    def _spend_trigger_grace_locked(
        self,
        elapsed: float,
    ) -> tuple[int, float]:
        """
        Consume Total Stop trigger-release grace before any pause budget.

        Returns:
            remaining grace seconds,
            elapsed time that must continue into pause accounting.
        """
        current = max(
            0.0,
            float(
                self.state.get(
                    "_triggerGraceFloat",
                    0.0,
                )
            ),
        )

        pause_elapsed = max(
            0.0,
            elapsed - current,
        )

        current = max(
            0.0,
            current - elapsed,
        )

        self.state["_triggerGraceFloat"] = current
        self.state["triggerGraceRemaining"] = int(
            ceil(current)
        )

        return (
            self.state["triggerGraceRemaining"],
            pause_elapsed,
        )


    def _charge_paid_pause_locked(
        self,
        elapsed: float,
    ) -> float:
        """
        Charge the dedicated PAUSE tariff.

        This tariff is independent from water/foam/etc.
        Default: 1000 sum / 120 sec.
        """
        if elapsed <= 0:
            return 0.0

        tariff = self.params.get(
            "paidPause",
            {},
        )

        if tariff.get("enabled") is False:
            return 0.0

        amount_sum = int(
            tariff.get("amountSum") or 0
        )

        duration_seconds = int(
            tariff.get("durationSeconds") or 0
        )

        if amount_sum <= 0 or duration_seconds <= 0:
            return 0.0

        current = float(
            self.state.get(
                "_creditFloat",
                self.state.get(
                    "creditSum",
                    0,
                ),
            )
        )

        next_credit = max(
            0.0,
            current
            - (
                amount_sum
                / duration_seconds
            )
            * elapsed,
        )

        spent_sum = max(
            0.0,
            current - next_credit,
        )

        self.state["_creditFloat"] = next_credit
        self.state["creditSum"] = int(
            ceil(next_credit)
        )

        return spent_sum


    def _spend_pause_budget_locked(self, elapsed: float) -> tuple[int, float]:
        current = float(self.state.get("_pauseBudgetFloat", self.state.get("freePauseRemaining", 0)))
        chargeable_elapsed = max(0.0, elapsed - current)
        current = max(0.0, current - elapsed)
        self.state["_pauseBudgetFloat"] = current
        remaining = int(ceil(current))
        self.state["freePauseRemaining"] = remaining
        return remaining, chargeable_elapsed

    def _get_io_sync(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{settings.io_helper_url}/io")
                response.raise_for_status()
                return response.json()
        except Exception:
            with self.lock:
                self.io_failures += 1
                self.state["lastIoOk"] = False
            raise

    def _get_rfid_events_sync(self, since: int | None = None) -> dict[str, Any]:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(
                f"{settings.io_helper_url}/rfid/events",
                params={"since": int(since or 0), "limit": 1000},
            )
            response.raise_for_status()
            return response.json()

    def _apply_output_sync(self, output: str | None) -> None:
        if output == self.last_output:
            return

        if output is not None and output not in MODE_OUTPUTS:
            raise ValueError(f"Unsupported output: {output}")

        try:
            with httpx.Client(timeout=3.0) as client:
                # Safe exclusive-output policy:
                # first force every wash output OFF,
                # then energize only the requested output.
                for name in sorted(MODE_OUTPUTS):
                    response = client.post(
                        f"{settings.io_helper_url}/outputs/{name}",
                        json={"on": False},
                    )
                    response.raise_for_status()

                if output is not None:
                    response = client.post(
                        f"{settings.io_helper_url}/outputs/{output}",
                        json={"on": True},
                    )
                    response.raise_for_status()

            self.last_output = output

        except Exception:
            self.last_output = None
            raise

    def _all_off_sync(self) -> None:
        try:
            with httpx.Client(timeout=3.0) as client:
                for name in sorted(MODE_OUTPUTS):
                    response = client.post(
                        f"{settings.io_helper_url}/outputs/{name}",
                        json={"on": False},
                    )
                    response.raise_for_status()

            self.last_output = None

        except Exception:
            self.last_output = None


wash_runtime = WashRuntime()
