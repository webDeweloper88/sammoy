import unittest
from unittest.mock import Mock,patch
from app.io_safety import validate_io,OUTPUTS
import test_wash_logic
from app import wash_logic
class IoSafetyTests(unittest.TestCase):
    def io(self):return {'inputs':{'total_stop':True},'modbus_ok':True,'poll_age_seconds':0,'outputs':dict.fromkeys(OUTPUTS,False),'controller_boot_id':'a','safety_trip_seq':0}
    def test_down_stale_or_missing_readback_rejected(self):
        for change in ({'modbus_ok':False},{'poll_age_seconds':2},{'poll_age_seconds':float('nan')},{'poll_age_seconds':True},{'outputs':{}},{'outputs':{**dict.fromkeys(OUTPUTS,False),'water':True}}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):validate_io({**self.io(),**change})
    def test_confirmed_single_output_only(self):
        io=self.io();io['outputs']['water']=True;validate_io(io,'water')
        io['outputs']['foam']=True
        with self.assertRaises(RuntimeError):validate_io(io,'water')
    def test_io_failure_preserves_credit_and_requires_explicit_selection(self):
        r=test_wash_logic.WashLogicTests().runtime(total_stop=True);r.state.update(creditSum=1000,_creditFloat=1000.0)
        r.select_mode('water');r._get_io_sync.return_value={**self.io(),'modbus_ok':False}
        with self.assertRaises(RuntimeError):r.tick()
        self.assertEqual(r.state['creditSum'],1000);self.assertFalse(r.state['lastIoOk']);self.assertIsNone(r.state['armedMode'])
        r._get_io_sync.return_value=self.io();r.tick();self.assertIsNone(r.state['requestedOutput']);self.assertEqual(r.state['creditSum'],1000)
    def test_partial_off_failure_still_attempts_all_relays(self):
        r=wash_logic.WashRuntime();client=Mock();response=Mock();response.json.return_value={'actual':False}
        client.post.side_effect=[RuntimeError('fast endpoint missing'),RuntimeError('first failed')]+[response]*7
        with patch.object(wash_logic,'sync_client') as factory:
            factory.return_value.__enter__.return_value=client
            self.assertFalse(r._all_off_sync())
        self.assertEqual(client.post.call_count,9);self.assertFalse(r.state['outputsOffConfirmed'])

    def test_failed_off_never_enables_next_output(self):
        r=wash_logic.WashRuntime();r._all_off_sync=Mock(return_value=False)
        with patch.object(wash_logic,'sync_client') as factory:
            with self.assertRaises(RuntimeError):r._apply_output_sync('water')
            factory.assert_not_called()
        self.assertEqual(r._all_off_sync.call_count,2)
    def test_unconfirmed_on_forces_off(self):
        r=wash_logic.WashRuntime();r._all_off_sync=Mock(return_value=True)
        response=Mock();response.json.return_value={'actual':False}
        with patch.object(wash_logic,'sync_client') as factory:
            factory.return_value.__enter__.return_value.post.return_value=response
            with self.assertRaises(RuntimeError):r._apply_output_sync('water')
        self.assertIsNone(r.last_output);self.assertEqual(r._all_off_sync.call_count,2)

    def test_slow_confirmed_off_renews_lease_before_on(self):
        from app.config import settings
        r=wash_logic.WashRuntime();events=[];clock=[0.0];deadline=[2.0]
        def slow_off():
            clock[0]+=3.0;events.append('off-confirmed');return True
        r._all_off_sync=Mock(side_effect=slow_off)
        heartbeat=Mock();heartbeat.json.return_value={'controller_lease_valid':True}
        on=Mock();on.json.return_value={'actual':True}
        client=Mock()
        def post(url,**kwargs):
            if url.endswith('/controller/heartbeat'):
                deadline[0]=clock[0]+2.0;events.append('heartbeat');return heartbeat
            self.assertLess(clock[0],deadline[0],'ON attempted with expired watchdog after slow OFF')
            events.append('on');return on
        client.post.side_effect=post
        with patch.object(wash_logic,'sync_client') as factory:
            factory.return_value.__enter__.return_value=client;r._apply_output_sync('foam')
        self.assertEqual(events,['off-confirmed','heartbeat','on']);self.assertEqual(r.last_output,'foam')
        self.assertEqual(client.post.call_args_list[1].kwargs,{'json':{'on':True}})
    def test_unconfirmed_lease_never_enables_output(self):
        r=wash_logic.WashRuntime();r._all_off_sync=Mock(return_value=True)
        response=Mock();response.json.return_value={'controller_lease_valid':False}
        with patch.object(wash_logic,'sync_client') as factory:
            factory.return_value.__enter__.return_value.post.return_value=response
            with self.assertRaises(RuntimeError):r._apply_output_sync('foam')
            self.assertEqual(factory.return_value.__enter__.return_value.post.call_count,1)
        self.assertIsNone(r.last_output);self.assertEqual(r._all_off_sync.call_count,2)

    def test_single_request_off_requires_complete_false_readback(self):
        r=wash_logic.WashRuntime();response=Mock();response.json.return_value={'off_confirmed':True,'outputs':dict.fromkeys(OUTPUTS,False)}
        with patch.object(wash_logic,'sync_client') as factory:
            client=factory.return_value.__enter__.return_value;client.post.return_value=response
            self.assertTrue(r._all_off_sync());self.assertEqual(client.post.call_count,1)
        self.assertTrue(r.state['outputsOffConfirmed'])
    def test_partial_fast_proof_falls_back_to_every_relay(self):
        r=wash_logic.WashRuntime();bad=Mock();bad.json.return_value={'off_confirmed':True,'outputs':{'foam':False}};off=Mock();off.json.return_value={'actual':False}
        with patch.object(wash_logic,'sync_client') as factory:
            client=factory.return_value.__enter__.return_value;client.post.side_effect=[bad]+[off]*8
            self.assertTrue(r._all_off_sync());self.assertEqual(client.post.call_count,9)

    def test_explicitly_absent_bill_acceptor_does_not_disable_modbus_proof(self):
        validate_io({**self.io(),'nv9_enabled':False,'nv9_listener_alive':False})
        for change in ({'nv9_enabled':True},{'nv9_enabled':0},{'modbus_ok':False},{'poll_age_seconds':3}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                validate_io({**self.io(),'nv9_enabled':False,'nv9_listener_alive':False,**change})
        with self.assertRaises(RuntimeError):validate_io({**self.io(),'nv9_listener_alive':False})
