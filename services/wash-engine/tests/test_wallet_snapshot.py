"""Wallet network waits must not make the read-only kiosk appear offline."""
import threading
import unittest
from unittest.mock import Mock, patch
import test_wash_logic
from app.wash_logic import WashRuntime
from app.wallet_post import freeze


class WalletSnapshotTests(unittest.TestCase):
    def test_slow_off_confirmation_serves_detached_pending_balance(self):
        runtime = WashRuntime()
        runtime.state.update(creditSum=33000, _creditFloat=33000.0)
        entered = threading.Event()
        release = threading.Event()
        def slow_off(_):
            entered.set()
            if not release.wait(2):
                raise AssertionError('Test did not release OFF confirmation')
        runtime._apply_output_sync = Mock(side_effect=slow_off)
        runtime._flush_usage_locked = Mock()
        runtime._heartbeat_session_locked = Mock()
        def transfer():
            with runtime.lock:
                try:
                    freeze(runtime)
                    runtime.state.update(creditSum=0, walletTransferPending=False)
                finally:
                    runtime._wallet_pending_snapshot = None
        thread = threading.Thread(target=transfer)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            result = runtime.snapshot()
            self.assertTrue(result['state']['walletTransferPending'])
            self.assertEqual(result['state']['creditSum'], 33000)
            self.assertIsNone(result['state']['requestedOutput'])
            result['state']['creditSum'] = 999
            self.assertEqual(runtime.snapshot()['state']['creditSum'], 33000)
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(runtime.snapshot()['state']['creditSum'], 0)
        self.assertFalse(runtime.snapshot()['state']['walletTransferPending'])

    def test_card_failure_clears_transient_snapshot_without_clearing_money(self):
        runtime = WashRuntime()
        runtime.shared_wallet_enabled = True
        runtime.state.update(creditSum=33000, _creditFloat=33000.0)
        runtime._apply_output_sync = Mock(side_effect=RuntimeError('No OFF acknowledgement'))
        with patch('app.wallet_post.pending_job', return_value=None):
            with runtime.lock:
                runtime._apply_rfid_card_locked('507EF458', {'sak': 8, 'atqa': '0400'})
        self.assertIsNone(runtime._wallet_pending_snapshot)
        self.assertEqual(runtime.snapshot()['state']['creditSum'], 33000)
        self.assertEqual(runtime.state['lastRfidStatus'], 'wallet_error')

    def test_reader_waiting_before_publication_sees_progress_without_unlock(self):
        runtime = WashRuntime()
        result = []
        with runtime.lock:
            reader = threading.Thread(target=lambda: result.append(runtime.snapshot()))
            reader.start()
            runtime.state['walletTransferPending'] = True
            runtime._publish_wallet_pending_locked()
            reader.join(0.5)
            finished = not reader.is_alive()
            runtime._wallet_pending_snapshot = None
        reader.join(1)
        self.assertTrue(finished, 'Snapshot waited for the whole financial operation')
        self.assertTrue(result[0]['state']['walletOperationInProgress'])
