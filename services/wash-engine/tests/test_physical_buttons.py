import unittest
from unittest.mock import Mock,patch
import test_wash_logic
from app.physical_buttons import PhysicalButtons,BUTTONS,MODES
from app.wash_logic import WashRuntime
from app.io_safety import OUTPUTS

class PhysicalButtonTests(unittest.TestCase):
    def packet(self,**changes):return {'input_events':dict.fromkeys(BUTTONS,0),'inputs':{},**changes}
    def test_short_press_is_consumed_once_and_counter_restart_is_not_a_press(self):
        b=PhysicalButtons();io=self.packet();self.assertIsNone(b.action(io))
        io['input_events']['mode_water']=1
        self.assertEqual(b.action(io),'water');self.assertIsNone(b.action(io))
        io['input_events']['mode_water']=0
        self.assertIsNone(b.action(io))
    def test_stop_has_priority_and_held_mode_does_not_restart_after_stop(self):
        b=PhysicalButtons();io=self.packet();b.action(io)
        io['input_events'].update(pause_button=1,mode_water=1)
        io['inputs']={'pause_button':True,'mode_water':True}
        self.assertEqual(b.action(io),'pause')
        io['inputs']['pause_button']=False
        self.assertIsNone(b.action(io))
        io['input_events']['mode_water']=2
        self.assertEqual(b.action(io),'water')
    def test_startup_stop_is_effective_but_startup_mode_is_not(self):
        self.assertEqual(PhysicalButtons().action(self.packet(inputs={'pause_button':True})),'pause')
        self.assertIsNone(PhysicalButtons().action(self.packet(inputs={'mode_water':True})))
    def test_conflicting_and_queued_multiple_presses_are_ignored(self):
        b=PhysicalButtons();io=self.packet();b.action(io)
        io['input_events'].update(mode_water=1,mode_foam=1)
        self.assertIsNone(b.action(io))
        io['input_events']['mode_water']=3
        self.assertIsNone(b.action(io))
    def runtime(self):
        r=WashRuntime();r.state.update(creditSum=10000,_creditFloat=10000.0)
        r._nv9_startup_pending=False;r.last_tick=100
        io={'nv9_enabled':False,'modbus_ok':True,'poll_age_seconds':0,'outputs':dict.fromkeys(OUTPUTS,False),'controller_boot_id':'buttons-test','safety_trip_seq':0,**self.packet()}
        def read():return {**io,'outputs':{k:k==r.last_output for k in OUTPUTS}}
        r._get_io_sync=Mock(side_effect=read)
        r._apply_output_sync=Mock(side_effect=lambda mode:setattr(r,'last_output',mode))
        r._all_off_sync=Mock(side_effect=lambda:setattr(r,'last_output',None))
        for name in ('_get_rfid_events_sync','_track_usage_locked','_flush_usage_locked','_maybe_cleanup_retention_locked','_close_session_locked','_heartbeat_session_locked'):
            setattr(r,name,Mock(return_value={}))
        return r,io
    def tick(self,r,at):
        with patch('app.wash_logic.time.monotonic',return_value=at):r.tick()
    def test_all_six_buttons_require_credit_and_trigger(self):
        for key,mode in MODES.items():
            r,io=self.runtime();self.tick(r,100.2)
            io['input_events'][key]=1;self.tick(r,100.4)
            self.assertEqual(r.state['armedMode'],mode);self.assertIsNone(r.last_output)
            io['inputs']['total_stop']=True;self.tick(r,100.6)
            self.assertEqual(r.last_output,mode)
    def test_physical_stop_keeps_balance_and_overrides_screen_while_held(self):
        r,io=self.runtime();self.tick(r,100.2);r.select_mode('water')
        io['inputs']['total_stop']=True;self.tick(r,100.4)
        balance=r.state['creditSum']
        io['input_events']['pause_button']=1;io['inputs']['pause_button']=True
        self.tick(r,100.6)
        self.assertIsNone(r.last_output);self.assertEqual(r.state['creditSum'],balance)
        self.assertEqual(r.state['selectedMode'],'pause')
        r.select_mode('foam');self.tick(r,100.8)
        self.assertIsNone(r.last_output);self.assertEqual(r.state['selectedMode'],'pause')
    def test_no_credit_locked_disabled_and_reconnect_do_not_start(self):
        for kind in ('credit','license','disabled','reconnect'):
            r,io=self.runtime();self.tick(r,100.2)
            if kind=='credit':r.state.update(creditSum=0,_creditFloat=0.0)
            if kind=='license':r.state['licenseLocked']=True
            if kind=='disabled':r.params['tariffs']['water']['enabled']=False
            if kind=='reconnect':r._io_fault('test connection lost')
            io['input_events']['mode_water']=1;self.tick(r,100.4)
            self.assertIsNone(r.last_output);self.assertIsNone(r.state['armedMode'])
    def test_stop_works_even_when_pause_is_disabled_in_ui(self):
        r,io=self.runtime();r.params['tariffs']['pause']['enabled']=False
        self.tick(r,100.2);r.select_mode('water');io['inputs']['total_stop']=True;self.tick(r,100.4)
        io['input_events']['pause_button']=1;self.tick(r,100.6)
        self.assertEqual(r.state['selectedMode'],'pause');self.assertIsNone(r.last_output)
    def test_air_and_vacuum_still_select_on_screen(self):
        for mode in ('air','vacuum'):
            r,io=self.runtime();self.tick(r,100.2);r.select_mode(mode)
            io['inputs']['total_stop']=True;self.tick(r,100.4)
            self.assertEqual(r.last_output,mode)

    def test_no_trigger_is_continuous_and_release_stops_after_configured_grace(self):
        r,io=self.runtime();self.tick(r,100.2);r.select_mode('water')
        io['inputs']['total_stop']=True;self.tick(r,100.4)
        self.assertEqual(r.last_output,'water')
        self.tick(r,100.6);self.assertEqual(r.last_output,'water')
        io['inputs']['total_stop']=False;self.tick(r,100.8)
        self.tick(r,102.0);self.assertIsNone(r.last_output)
        self.tick(r,104.0);self.assertIsNone(r.last_output)
        self.assertFalse(r.state['totalStopActive'])
