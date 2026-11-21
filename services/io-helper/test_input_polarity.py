import copy,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock
from fastapi import HTTPException
from pydantic import ValidationError
import main
from pulse_journal import PulseJournal

class InputPolarityTests(unittest.TestCase):
    def setUp(self):
        self.old=dict(main.APP_STATE);self.state=copy.deepcopy(main.io_state)
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'nv9.sqlite3')
        self.journal=PulseJournal(self.path);self.journal.increment()
        self.cfg={'inputs':[{'name':str(i),'address':i,'active_low':True} for i in range(8)],'bill_acceptor':{'active_low':True}}
        self.controller=Mock(cfg=self.cfg);self.controller.read_outputs.return_value=[False]*8
        main.APP_STATE.update(controller=self.controller,pulse_counter=self.journal)
        main.io_state.update(modbus_ok=True,last_poll_monotonic=time.monotonic())
    def tearDown(self):
        main.APP_STATE.clear();main.APP_STATE.update(self.old);main.io_state.clear();main.io_state.update(self.state)
        self.journal.close();self.tmp.cleanup()
    def test_change_survives_restart_without_cash_or_stream_changes(self):
        stream=self.journal.stream_id
        main.input_polarity(main.InputPolarityRequest(active_low=False))
        self.assertTrue(all(i['active_low'] is False for i in self.cfg['inputs']))
        self.assertTrue(self.cfg['bill_acceptor']['active_low'])
        self.assertEqual(self.journal.value(),1);self.assertEqual(stream,self.journal.stream_id)
        self.journal.close();self.journal=PulseJournal(self.path)
        fresh=copy.deepcopy(self.cfg)
        for i in fresh['inputs']:i['active_low']=True
        main.restore_input_polarity(fresh,self.journal)
        self.assertTrue(all(i['active_low'] is False for i in fresh['inputs']))
        self.assertEqual(main.io_state['inputs'],{})
        self.controller.write_output.assert_not_called()
    def test_refuses_energized_incomplete_stale_and_fog(self):
        for raw,age,kind in [([True]+[False]*7,0,'wash'),([False]*7,0,'wash'),([False]*8,4,'wash'),([False]*8,0,'dry_fog')]:
            with self.subTest(raw=raw,age=age,kind=kind):
                self.controller.read_outputs.return_value=raw;self.cfg['device_type']=kind
                main.io_state.update(modbus_ok=True,last_poll_monotonic=time.monotonic()-age)
                with self.assertRaises(HTTPException):main.input_polarity(main.InputPolarityRequest(active_low=False))
                self.assertIsNone(self.journal.get_setting('io_input_polarity'))
    def test_override_does_not_leak_into_changed_profile(self):
        main.input_polarity(main.InputPolarityRequest(active_low=False))
        changed=copy.deepcopy(self.cfg);changed['inputs'][0]['name']='different'
        for i in changed['inputs']:i['active_low']=True
        main.restore_input_polarity(changed,self.journal)
        self.assertTrue(all(i['active_low'] for i in changed['inputs']))
    def test_rejects_non_boolean(self):
        for value in ['false',0,None]:
            with self.assertRaises(ValidationError):main.InputPolarityRequest(active_low=value)
