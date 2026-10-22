import unittest
from unittest.mock import Mock, patch
import test_dry_fog_runtime as fog_tests
from app.wash_logic import WashRuntime, normalize_parameters
from app.dry_fog_purge import cancel
from app.wallet_post import freeze


class PurgeTests(unittest.TestCase):
    def runtime(self):
        r=fog_tests.DryFogRuntimeTests().runtime(0)
        r.params['purge']={'enabled':True,'idleSeconds':7200,'durationSeconds':30}
        r._purge_idle_since=100
        r._record_credit_locked=Mock()
        r._heartbeat_session_locked=Mock()
        return r

    def tick(self,r,at):
        with patch('app.wash_logic.time.monotonic',return_value=at):r.tick()

    def test_idle_schedule_has_no_customer_session_usage_or_money(self):
        r=self.runtime();self.tick(r,7299);self.assertIsNone(r.last_output)
        self.tick(r,7300);self.assertEqual(r.last_output,'purge')
        self.assertTrue(r.state['purgeActive']);self.assertIsNone(r.state['activeMode'])
        self.assertEqual(r.state['purgeRemainingSeconds'],30)
        self.tick(r,7310);self.assertEqual(r.state['purgeRemainingSeconds'],20)
        self.tick(r,7330);self.assertIsNone(r.last_output)
        self.assertFalse(r.state['purgeActive']);self.assertEqual(r.state['creditSum'],0)
        r._track_usage_locked.assert_not_called();r._record_credit_locked.assert_not_called()
        self.assertIsNone(r.active_session_id)
        self.tick(r,14529);self.assertIsNone(r.last_output)
        self.tick(r,14530);self.assertEqual(r.last_output,'purge')

    def test_balance_session_transfer_held_cash_license_and_recovery_block_start(self):
        for key,value in [('creditSum',10000),('walletTransferPending',True),('walletCashHeld',1000),('licenseLocked',True),('powerRecoveryAvailable',True)]:
            with self.subTest(key=key):
                r=self.runtime();r.state[key]=value
                if key=='creditSum':r.state['_creditFloat']=10000.0
                self.tick(r,7400);self.assertNotEqual(r.last_output,'purge')
        r=self.runtime();r.active_session_id=99
        self.tick(r,7400);self.assertNotEqual(r.last_output,'purge')

    def test_cash_manual_click_and_card_stop_before_credit_or_transfer(self):
        for source in ('cash','manual','click','card'):
            with self.subTest(source=source):
                r=self.runtime();self.tick(r,7300);self.assertEqual(r.last_output,'purge')
                def record(*args,**kwargs):self.assertIsNone(r.last_output)
                r._record_credit_locked.side_effect=record
                if source=='cash':r._accept_cash_locked(10000,'bill_pulse',10,{})
                elif source=='manual':r.add_credit(10000,'admin')
                elif source=='click':
                    with patch('app.bonus_credit.accept',side_effect=record):r.add_credit(10000,'click')
                else:freeze(r)
                self.assertIsNone(r.last_output);self.assertFalse(r.state['purgeActive'])

    def test_disabled_or_restart_timer_does_not_run_immediately(self):
        r=self.runtime();r.params['purge']['enabled']=False
        self.tick(r,7400);self.assertIsNone(r.last_output)
        r.params['purge']['enabled']=True
        self.tick(r,7401);self.assertIsNone(r.last_output)
        self.assertFalse(WashRuntime('dry_fog').params['purge']['enabled'])
        r=WashRuntime('dry_fog');self.assertIsNone(r._purge_until)

    def test_fault_clears_maintenance_and_restarts_idle_wait(self):
        r=self.runtime();self.tick(r,7300)
        with patch('app.wash_logic.time.monotonic',return_value=7301):r._io_fault('modbus unavailable')
        self.assertFalse(r.state['purgeActive']);self.assertIsNone(r._purge_until)
        self.tick(r,7302);self.assertNotEqual(r.last_output,'purge')

    def test_purge_cannot_be_selected_as_customer_mode_or_requested_directly(self):
        for kind in ('wash','dry_fog'):
            r=WashRuntime(kind)
            with self.assertRaises(ValueError):r.select_mode('purge')
            with self.assertRaises(ValueError):r._apply_output_sync('purge')

    def test_validation_bounds_and_defaults(self):
        self.assertEqual(normalize_parameters(None,'dry_fog')['purge'],{'enabled':False,'idleSeconds':7200,'durationSeconds':30})
        for bad in ({'idleSeconds':0},{'idleSeconds':61.5},{'durationSeconds':301},{'durationSeconds':0},{'enabled':'yes'}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):normalize_parameters({'purge':bad},'dry_fog')

    def test_technical_on_still_requires_off_lease_and_readback(self):
        r=WashRuntime('dry_fog')
        r.state['purgeActive']=True;r._purge_until=9999999999
        off=Mock();off.json.return_value={'off_confirmed':True,'outputs':dict.fromkeys(r.all_outputs,False)}
        lease=Mock();lease.json.return_value={'controller_lease_valid':True}
        on=Mock();on.json.return_value={'actual':True}
        with patch('app.wash_logic.sync_client') as factory:
            client=factory.return_value.__enter__.return_value
            client.post.side_effect=[off,lease,on]
            r._apply_output_sync('purge')
            self.assertEqual(r.last_output,'purge')
            self.assertTrue(client.post.call_args_list[-1].args[0].endswith('/outputs/purge'))
        r=WashRuntime('dry_fog');r.state['purgeActive']=True;r._purge_until=9999999999
        r._all_off_sync=Mock(return_value=False)
        with patch('app.wash_logic.sync_client') as factory:
            with self.assertRaises(RuntimeError):r._apply_output_sync('purge')
            factory.assert_not_called()

    def test_lock_or_pending_transfer_cancels_running_purge(self):
        for flag in ('licenseLocked','walletTransferPending','deviceProfileMismatch'):
            with self.subTest(flag=flag):
                r=self.runtime();self.tick(r,7300)
                r.state[flag]=True
                self.tick(r,7301)
                self.assertIsNone(r.last_output)
                self.assertFalse(r.state['purgeActive'])
                self.assertIsNone(r._purge_until)
