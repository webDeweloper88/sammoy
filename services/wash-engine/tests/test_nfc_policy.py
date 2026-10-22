import unittest
from unittest.mock import Mock, patch
from app.wash_logic import WashRuntime


class NfcPolicyTests(unittest.TestCase):
    def test_rejected_targets_never_reach_wallet_or_change_credit(self):
        for metadata in ({}, {'sak': 32, 'atqa': '0400'},
                         {'sak': 40, 'atqa': '4403'}, {'sak': True, 'atqa': '0400'},
                         {'sak': 8, 'atqa': 'xxxx'}):
            with self.subTest(metadata=metadata):
                runtime = WashRuntime()
                runtime.state['creditSum'] = 12345
                with patch('app.wallet_post.freeze') as freeze, patch('app.wash_logic.db') as database:
                    runtime._apply_rfid_card_locked('01020304', metadata)
                freeze.assert_not_called()
                database.assert_not_called()
                self.assertEqual(runtime.state['creditSum'], 12345)
                self.assertEqual(runtime.state['lastRfidStatus'], 'nfc_unsupported')

    def test_plain_card_reaches_existing_wallet_without_registration(self):
        runtime = WashRuntime()
        runtime.shared_wallet_enabled = True
        with patch('app.wallet_post.freeze', side_effect=RuntimeError('test reached wallet')) as freeze, patch('app.wallet_post.pending_job', return_value=None):
            runtime._apply_rfid_card_locked('01020304', {'sak': 8, 'atqa': '0400'})
        freeze.assert_called_once_with(runtime)
        self.assertNotEqual(runtime.state['lastRfidStatus'], 'nfc_unsupported')
