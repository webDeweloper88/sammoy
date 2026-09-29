import os
import unittest
from unittest.mock import Mock, patch


os.environ.setdefault("WASH_ENGINE_DEFAULT_OWNER_PASSWORD", "test-owner-password")
os.environ.setdefault("WASH_ENGINE_DEFAULT_ADMIN_PASSWORD", "test-admin-password")

from app.wash_logic import LEDGER_FLUSH_SECONDS, WashRuntime, normalize_parameters  # noqa: E402


def io_payload(*, total_stop=False, bill_pulses=0, coin_pulses=0):
    return {
        "inputs": [
            {"name": "bill_pulse", "rising_count": bill_pulses},
            {"name": "coin_pulse", "rising_count": coin_pulses},
            {"name": "total_stop_switch", "active": total_stop},
        ]
    }


class WashLogicTests(unittest.TestCase):
    def runtime(self, *, total_stop=False, bill_pulses=0, coin_pulses=0):
        runtime = WashRuntime()
        runtime._get_io_sync = Mock(
            return_value=io_payload(
                total_stop=total_stop,
                bill_pulses=bill_pulses,
                coin_pulses=coin_pulses,
            )
        )
        runtime._get_rfid_events_sync = Mock(return_value={})
        runtime._apply_output_sync = Mock()
        runtime._all_off_sync = Mock()
        runtime._record_credit_locked = Mock()
        runtime._track_usage_locked = Mock()
        runtime._flush_usage_locked = Mock()
        runtime._maybe_cleanup_retention_locked = Mock()
        runtime._close_session_locked = Mock()
        return runtime

    def tick_at(self, runtime, monotonic_time):
        with patch("app.wash_logic.time.monotonic", return_value=monotonic_time):
            runtime.tick()

    def test_default_tariffs_enable_all_eight_outputs_and_require_trigger(self):
        params = normalize_parameters(None)
        self.assertEqual(params["tariffs"]["water"]["sumPerMinute"], 1500)
        self.assertEqual(params["tariffs"]["osmos"]["sumPerMinute"], 3000)
        self.assertTrue(params["tariffs"]["air"]["enabled"])
        self.assertTrue(params["requireTotalStopTrigger"])

    def test_usage_ledger_flush_interval_limits_database_writes(self):
        self.assertEqual(LEDGER_FLUSH_SECONDS, 5.0)

    def test_zero_credit_cannot_arm_mode(self):
        runtime = self.runtime()
        state = runtime.select_mode("water")["state"]
        self.assertEqual(state["phase"], "no_credit")
        self.assertEqual(state["selectedMode"], "pause")
        self.assertIsNone(state["armedMode"])

    def test_explicitly_disabled_air_cannot_be_selected(self):
        runtime = self.runtime()
        runtime.state["creditSum"] = 1000
        runtime.params["tariffs"]["air"]["enabled"] = False
        with self.assertRaisesRegex(ValueError, "disabled"):
            runtime.select_mode("air")

    def test_switching_mode_preserves_shared_pause_budget(self):
        runtime = self.runtime()
        runtime.state["creditSum"] = 1000

        runtime.select_mode("water")
        runtime.state["freePauseRemaining"] = 41
        runtime.state["_pauseBudgetFloat"] = 40.5
        runtime.select_mode("water")
        self.assertEqual(runtime.state["freePauseRemaining"], 41)
        self.assertEqual(runtime.state["_pauseBudgetFloat"], 40.5)

        runtime.select_mode("foam")
        self.assertEqual(runtime.state["freePauseRemaining"], 41)
        self.assertEqual(runtime.state["_pauseBudgetFloat"], 40.5)

    def test_entering_pause_preserves_shared_pause_budget(self):
        runtime = self.runtime()
        runtime.state["creditSum"] = 1000
        runtime.select_mode("osmos")
        runtime.state["freePauseRemaining"] = 17
        runtime.state["_pauseBudgetFloat"] = 16.5

        runtime.select_mode("pause")
        self.assertEqual(runtime.state["freePauseRemaining"], 17)
        self.assertEqual(runtime.state["_pauseBudgetFloat"], 16.5)

        runtime.state["freePauseRemaining"] = 42
        runtime.state["_pauseBudgetFloat"] = 41.5
        runtime.select_mode("pause")
        self.assertEqual(runtime.state["freePauseRemaining"], 42)
        self.assertEqual(runtime.state["_pauseBudgetFloat"], 41.5)

    def test_waiting_for_trigger_uses_free_pause_then_charges(self):
        runtime = self.runtime(total_stop=False)
        runtime.params["requireTotalStopTrigger"] = True
        runtime.state["creditSum"] = 1000
        runtime.state["_creditFloat"] = 1000.0
        runtime.select_mode("water")
        runtime.last_tick = 100.0

        self.tick_at(runtime, 120.0)
        self.assertEqual(runtime.state["phase"], "pause_free")
        self.assertEqual(runtime.state["freePauseRemaining"], 41)  # 1 s grace, then 19 s free pause
        self.assertEqual(runtime.state["creditSum"], 1000)
        self.assertIsNone(runtime.state["requestedOutput"])

        self.tick_at(runtime, 170.0)
        self.assertEqual(runtime.state["phase"], "pause_paid")
        self.assertEqual(runtime.state["freePauseRemaining"], 0)
        self.assertEqual(runtime.state["creditSum"], 925)  # remaining 41 s free + 9 s at 500 sum/min
        self.assertIsNone(runtime.state["requestedOutput"])

    def test_active_mode_charges_selected_tariff_and_requests_one_output(self):
        runtime = self.runtime(total_stop=True)
        runtime.state["creditSum"] = 1000
        runtime.state["_creditFloat"] = 1000.0
        runtime.select_mode("water")
        runtime.last_tick = 100.0

        self.tick_at(runtime, 110.0)
        self.assertEqual(runtime.state["phase"], "active")
        self.assertEqual(runtime.state["activeMode"], "water")
        self.assertEqual(runtime.state["requestedOutput"], "water")
        self.assertEqual(runtime.state["creditSum"], 750)
        runtime._apply_output_sync.assert_called_once_with("water")

    def test_mode_activates_without_optional_trigger_input(self):
        runtime = self.runtime(total_stop=False)
        runtime.params["requireTotalStopTrigger"] = False
        runtime.state["creditSum"] = 1000
        runtime.state["_creditFloat"] = 1000.0
        runtime.select_mode("nano")
        runtime.last_tick = 100.0

        self.tick_at(runtime, 101.0)

        self.assertEqual(runtime.state["phase"], "active")
        self.assertEqual(runtime.state["requestedOutput"], "nano")
        runtime._apply_output_sync.assert_called_once_with("nano")

    def test_expired_manual_pause_never_resumes_output_with_held_trigger(self):
        runtime = self.runtime(total_stop=True)
        runtime.state["creditSum"] = 2000
        runtime.state["_creditFloat"] = 2000.0
        runtime.select_mode("osmos")
        runtime.select_mode("pause")
        runtime.state["freePauseRemaining"] = 0
        runtime.state["_pauseBudgetFloat"] = 0.0
        runtime.last_tick = 100.0

        self.tick_at(runtime, 101.0)

        self.assertEqual(runtime.state["phase"], "pause_paid")
        self.assertEqual(runtime.state["selectedMode"], "pause")
        self.assertIsNone(runtime.state["activeMode"])
        self.assertIsNone(runtime.state["requestedOutput"])
        self.assertTrue(runtime._apply_output_sync.call_args_list)
        self.assertTrue(all(call.args == (None,) for call in runtime._apply_output_sync.call_args_list))

    def test_expired_manual_pause_charges_but_keeps_relay_off_without_trigger(self):
        runtime = self.runtime(total_stop=False)
        runtime.state["creditSum"] = 2000
        runtime.state["_creditFloat"] = 2000.0
        runtime.select_mode("osmos")
        runtime.select_mode("pause")
        runtime.state["freePauseRemaining"] = 0
        runtime.state["_pauseBudgetFloat"] = 0.0
        runtime.last_tick = 100.0

        self.tick_at(runtime, 101.0)

        self.assertEqual(runtime.state["phase"], "pause_paid")
        self.assertIsNone(runtime.state["activeMode"])
        self.assertIsNone(runtime.state["requestedOutput"])
        self.assertLess(runtime.state["creditSum"], 2000)
        self.assertTrue(runtime._apply_output_sync.call_args_list)
        self.assertTrue(all(call.args == (None,) for call in runtime._apply_output_sync.call_args_list))

    def test_switching_tariff_never_creates_credit(self):
        runtime = self.runtime()
        runtime.state["creditSum"] = 5000
        runtime.state["_creditFloat"] = 5000.0

        runtime.select_mode("water")
        runtime._charge_active_locked("water", 10)
        self.assertEqual(runtime.state["creditSum"], 4750)

        runtime.select_mode("vacuum")
        self.assertEqual(runtime.state["creditSum"], 4750)
        runtime._charge_active_locked("vacuum", 10)
        self.assertEqual(runtime.state["creditSum"], 4250)

        runtime.select_mode("water")
        self.assertEqual(runtime.state["creditSum"], 4250)

    def test_fractional_credit_is_not_closed_early(self):
        runtime = self.runtime()
        runtime.params["tariffs"]["water"] = {
            "amountSum": 1000,
            "durationSeconds": 3,
            "enabled": True,
        }
        runtime.state["creditSum"] = 1
        runtime.state["_creditFloat"] = 0.75

        runtime._charge_active_locked("water", 0.001)

        self.assertGreater(runtime.state["_creditFloat"], 0)
        self.assertEqual(runtime.state["creditSum"], 1)

    def test_fractional_ledger_spending_is_carried_between_flushes(self):
        runtime = self.runtime()

        runtime.pending_usage["spent_sum"] = 10.4
        self.assertEqual(runtime._take_ledger_spent_locked(), 10)
        self.assertAlmostEqual(runtime.ledger_spent_carry, 0.4)

        runtime.pending_usage["spent_sum"] = 10.7
        self.assertEqual(runtime._take_ledger_spent_locked(), 11)
        self.assertAlmostEqual(runtime.ledger_spent_carry, 0.1)

        runtime.pending_usage["spent_sum"] = 0.6
        self.assertEqual(runtime._take_ledger_spent_locked(settle=True), 1)
        self.assertEqual(runtime.ledger_spent_carry, 0.0)

    def test_pulse_counter_adds_only_positive_delta(self):
        runtime = self.runtime(bill_pulses=21)
        runtime.last_bill_pulses = 20
        runtime.last_tick = 100.0

        self.tick_at(runtime, 100.0)
        self.assertEqual(runtime.state["creditSum"], 1000)
        runtime._record_credit_locked.assert_called_once()

        self.tick_at(runtime, 101.0)
        self.assertEqual(runtime.state["creditSum"], 1000)
        runtime._record_credit_locked.assert_called_once()

    def test_license_lock_forces_output_off_and_rejects_customer_credit(self):
        runtime = self.runtime(total_stop=True)
        runtime.state["creditSum"] = 1000
        runtime.state["selectedMode"] = "water"
        runtime.state["armedMode"] = "water"
        runtime.state["activeMode"] = "water"
        runtime.state["requestedOutput"] = "water"

        runtime.set_license_status(True, "expired")
        self.assertEqual(runtime.state["phase"], "license_locked")
        self.assertIsNone(runtime.state["requestedOutput"])
        runtime._all_off_sync.assert_called_once()

        runtime.add_credit(5000, source="click")
        self.assertEqual(runtime.state["creditSum"], 1000)


if __name__ == "__main__":
    unittest.main()
