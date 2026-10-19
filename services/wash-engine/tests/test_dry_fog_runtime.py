"""No real I/O or money: exercise the same runtime control loop as wash."""
import unittest
from unittest.mock import Mock, patch
import test_wash_logic  # test environment defaults
from app.wash_logic import WashRuntime, normalize_parameters
from app.device_profiles import profile


class DryFogRuntimeTests(unittest.TestCase):
    def runtime(self, credit=10000):
        r=WashRuntime('dry_fog')
        r.last_tick=100.0
        r.state.update(creditSum=credit,_creditFloat=float(credit))
        self.trigger=False
        def io():
            return {'device_type':'dry_fog','inputs':{'total_stop':self.trigger},
                    'outputs':{name:name==r.last_output for name in r.all_outputs},
                    'modbus_ok':True,'poll_age_seconds':0,'nv9_enabled':False,
                    'controller_boot_id':'fog-test','safety_trip_seq':0}
        def apply(output):r.last_output=output
        r._get_io_sync=Mock(side_effect=io)
        r._apply_output_sync=Mock(side_effect=apply)
        r._all_off_sync=Mock(side_effect=lambda:apply(None))
        for name in ('_get_rfid_events_sync','_track_usage_locked','_flush_usage_locked','_maybe_cleanup_retention_locked','_close_session_locked'):
            setattr(r,name,Mock(return_value={}))
        return r

    def tick(self,r,at):
        with patch('app.wash_logic.time.monotonic',return_value=at):r.tick()

    def test_all_seven_services_start_without_trigger_and_bill_confirmed_time(self):
        for mode in profile('dry_fog')['client_programs']:
            with self.subTest(mode=mode):
                r=self.runtime();r.select_mode(mode)
                self.tick(r,100.2)
                self.assertEqual(r.last_output,mode)
                self.assertEqual(r.state['creditSum'],10000)  # no charge before ON proof
                self.tick(r,101.2)
                self.assertEqual(r.state['creditSum'],9000)
                self.assertEqual(r.state['activeMode'],mode)
                self.assertFalse(r.state['resumeRequiresTriggerReset'])

    def test_switch_preserves_credit_and_free_pause_budget(self):
        r=self.runtime();r.select_mode('aroma_1');self.tick(r,100.2)
        r.state.update(_pauseBudgetFloat=211.0,freePauseRemaining=211)
        r.select_mode('tank_air');self.tick(r,100.4)
        self.assertEqual(r.last_output,'tank_air');self.assertEqual(r.state['creditSum'],10000)
        self.assertEqual(r.state['freePauseRemaining'],211)
        self.trigger=True;self.tick(r,101.4)
        self.assertEqual(r.last_output,'tank_air');self.assertEqual(r.state['creditSum'],9000)

    def test_zero_balance_stops_and_new_money_does_not_auto_start(self):
        r=self.runtime(1000);r.select_mode('blackening');self.tick(r,100.2);self.tick(r,101.2)
        self.assertIsNone(r.last_output);self.assertEqual(r.state['creditSum'],0)
        self.assertIsNone(r.state['armedMode'])
        r.state.update(creditSum=10000,_creditFloat=10000.0);self.tick(r,102.2)
        self.assertIsNone(r.last_output)

    def test_rejects_wash_modes_and_technical_purge_without_io(self):
        r=self.runtime()
        for mode in ('water','air','vacuum','purge','unknown'):
            with self.assertRaises(ValueError):r.select_mode(mode)
            with self.assertRaises(ValueError):WashRuntime._apply_output_sync(r,mode)
        r._get_io_sync.assert_not_called()

    def test_pause_has_no_trigger_interlock_and_no_auto_resume(self):
        r=self.runtime();self.trigger=True;r.select_mode('aroma_3');self.tick(r,100.2)
        r.select_mode('pause');self.assertIsNone(r.last_output)
        self.tick(r,101.2);self.assertEqual(r.state['freePauseRemaining'],299)
        self.assertFalse(r.state['resumeRequiresTriggerReset'])
        self.tick(r,401.2);self.assertIsNone(r.last_output)
        self.assertEqual(r.state['pauseState'],'paid')
        self.assertEqual(r.state['creditSum'],9750)

    def test_disabled_service_and_pause_are_rejected(self):
        r=self.runtime();r.params=normalize_parameters({'pauseEnabled':False,'tariffs':{'aroma_2':{'enabled':False}}},'dry_fog')
        for mode in ('pause','aroma_2'):
            with self.assertRaises(ValueError):r.select_mode(mode)

    def test_parameters_are_separate_and_ignore_old_trigger_setting(self):
        r=self.runtime();self.assertEqual(r.parameter_key,'dry_fog_parameters')
        p=normalize_parameters({'requireTotalStopTrigger':True,'tariffs':{'water':{'enabled':True}}},'dry_fog')
        self.assertFalse(p['requireTotalStopTrigger']);self.assertNotIn('water',p['tariffs'])
        self.assertEqual(p['freePauseSeconds'],300);self.assertEqual(p['paidPause']['amountSum'],250)
        self.assertEqual(normalize_parameters(None)['freePauseSeconds'],60)
        self.assertTrue(normalize_parameters(None)['requireTotalStopTrigger'])

    def test_fault_preserves_money_and_requires_explicit_selection(self):
        r=self.runtime();r.select_mode('aroma_1');self.tick(r,100.2)
        good=r._get_io_sync.side_effect
        r._get_io_sync.side_effect=lambda:{**good(),'modbus_ok':False}
        with self.assertRaises(RuntimeError):self.tick(r,101.2)
        self.assertEqual(r.state['creditSum'],10000);self.assertIsNone(r.last_output)
        r._get_io_sync.side_effect=good;self.tick(r,102.2)
        self.assertIsNone(r.last_output);self.assertIsNone(r.state['armedMode'])

    def test_switch_off_failure_never_sends_on_and_includes_purge_in_off_sweep(self):
        r=WashRuntime('dry_fog');r._all_off_sync=Mock(return_value=False)
        with patch('app.wash_logic.sync_client') as client:
            with self.assertRaises(RuntimeError):r._apply_output_sync('aroma_1')
            client.assert_not_called()
        r=WashRuntime('dry_fog');response=Mock();response.json.return_value={'actual':False}
        with patch('app.wash_logic.sync_client') as factory:
            client=factory.return_value.__enter__.return_value
            client.post.side_effect=[RuntimeError('no fast proof')]+[response]*8
            self.assertTrue(r._all_off_sync())
            self.assertEqual(client.post.call_count,9)
            self.assertTrue(any(c.args[0].endswith('/outputs/purge') for c in client.post.call_args_list))

    def test_start_is_blocked_until_wallet_migration(self):
        r=WashRuntime('dry_fog')
        with patch.object(r,'load_parameters') as load:
            with self.assertRaisesRegex(RuntimeError,'migration'):r.start()
            load.assert_not_called()

    def test_confirmed_switch_is_off_then_lease_then_on_for_each_service(self):
        for mode in profile('dry_fog')['client_programs']:
            with self.subTest(mode=mode):
                r=WashRuntime('dry_fog');r.last_output='aroma_1' if mode!='aroma_1' else 'tank_air'
                off=Mock();off.json.return_value={'off_confirmed':True,'outputs':dict.fromkeys(r.all_outputs,False)}
                lease=Mock();lease.json.return_value={'controller_lease_valid':True}
                on=Mock();on.json.return_value={'actual':True}
                with patch('app.wash_logic.sync_client') as factory:
                    client=factory.return_value.__enter__.return_value
                    client.post.side_effect=[off,lease,on]
                    r._apply_output_sync(mode)
                    self.assertTrue(client.post.call_args_list[0].args[0].endswith('/controller/all-off'))
                    self.assertTrue(client.post.call_args_list[1].args[0].endswith('/controller/heartbeat'))
                    self.assertTrue(client.post.call_args_list[2].args[0].endswith('/outputs/'+mode))
                    self.assertEqual(r.last_output,mode)

    def test_unconfirmed_on_attempts_off_and_keeps_last_output_empty(self):
        r=WashRuntime('dry_fog');r._all_off_sync=Mock(return_value=True)
        lease=Mock();lease.json.return_value={'controller_lease_valid':True}
        on=Mock();on.json.return_value={'actual':False}
        with patch('app.wash_logic.sync_client') as factory:
            factory.return_value.__enter__.return_value.post.side_effect=[lease,on]
            with self.assertRaisesRegex(RuntimeError,'ON readback'):r._apply_output_sync('blackening')
        self.assertIsNone(r.last_output);self.assertEqual(r._all_off_sync.call_count,2)

    def test_null_pause_uses_device_default(self):
        self.assertEqual(normalize_parameters({'freePauseSeconds':None},'dry_fog')['freePauseSeconds'],300)
        self.assertEqual(normalize_parameters({'freePauseSeconds':None})['freePauseSeconds'],60)

    def test_disabling_running_service_stops_without_restarting_when_reenabled(self):
        r=self.runtime();r.select_mode('aroma_1');self.tick(r,100.2)
        r.params['tariffs']['aroma_1']['enabled']=False
        self.tick(r,100.4);self.assertIsNone(r.last_output)
        self.assertIsNone(r.state['armedMode']);self.assertEqual(r.state['creditSum'],10000)
        r.params['tariffs']['aroma_1']['enabled']=True
        self.tick(r,100.6);self.assertIsNone(r.last_output)
