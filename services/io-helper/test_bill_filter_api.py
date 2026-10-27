import tempfile,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timedelta
from itertools import product
from unittest.mock import Mock,patch
from fastapi import HTTPException
import main
from bill_filter import BillFilter,PRESETS
from pulse_journal import PulseJournal

class BillFilterApiTests(unittest.TestCase):
    def test_process_reader_settings_restart_without_changing_counter(self):
        from bill_process_reader import ProcessLevelReader
        reader=ProcessLevelReader(self.line,True,False,0,5)
        reader.reconfigure=Mock();main.APP_STATE['bill_reader']=reader
        self.journal.increment();identity=self.journal.stream_id
        main.bill_filter_write({'min_pulse_ms':25,'min_gap_ms':25})
        self.assertEqual(reader.reconfigure.call_count,1)
        self.assertEqual(reader.reconfigure.call_args.args[0:2],(True,False))
        self.assertEqual(reader.reconfigure.call_args.args[3],25)
        self.assertEqual(self.journal.value(),1);self.assertEqual(self.journal.stream_id,identity)

    def test_process_reader_restart_failure_blocks_credit_and_preserves_counter(self):
        from bill_process_reader import ProcessLevelReader
        reader=ProcessLevelReader(self.line,True,False,0,5)
        reader.reconfigure=Mock(side_effect=RuntimeError('failed'))
        main.APP_STATE['bill_reader']=reader
        self.journal.increment()
        with self.assertRaises(HTTPException) as error:main.bill_filter_write({'min_pulse_ms':25})
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(main.APP_STATE['bill_filter'].fault,'reader_failed')
        self.assertEqual(self.journal.value(),1)
    def setUp(self):
        self.old=dict(main.APP_STATE);self.tmp=tempfile.TemporaryDirectory()
        self.journal=PulseJournal(str(Path(self.tmp.name)/'counter.sqlite3'))
        self.line=Mock();self.line.get_value.return_value=1;self.line.event_wait.return_value=False
        main.APP_STATE.update(pulse_counter=self.journal,nv9_enabled=True,bill_line=self.line,bill_filter=BillFilter({},False,0))
        main.APP_STATE['bill_filter'].poll(1)
    def tearDown(self):
        main.APP_STATE.clear();main.APP_STATE.update(self.old);self.journal.close();self.tmp.cleanup()
    def test_save_is_persistent_and_does_not_reset_or_credit_counter(self):
        self.journal.increment();identity=self.journal.stream_id
        r=main.bill_filter_write(PRESETS['standard_50_100ms'])
        self.assertEqual(r['settings']['max_pulse_ms'],250)
        self.assertEqual(self.journal.value(),1);self.assertEqual(self.journal.stream_id,identity)
        self.assertEqual(self.journal.get_setting('bill_filter'),r['settings'])
    def test_queued_events_active_signal_and_bad_config_are_rejected(self):
        self.line.event_wait.return_value=True
        with self.assertRaises(HTTPException):main.bill_filter_write({})
        self.line.event_wait.return_value=False;self.line.get_value.return_value=0
        with self.assertRaises(HTTPException):main.bill_filter_write({})
        with self.assertRaises(HTTPException):main.bill_filter_write({'max_pulse_ms':0})
    def test_fault_is_not_cleared_by_save_and_reset_never_changes_money(self):
        f=main.APP_STATE['bill_filter'];f.fault='excessive_rate'
        self.journal.increment();self.journal.set_setting('bill_filter_fault',f.fault)
        main.bill_filter_write({})
        self.assertEqual(main.APP_STATE['bill_filter'].fault,'excessive_rate')
        main.APP_STATE['bill_filter'].inactive_since=0
        self.line.get_value.return_value=0
        with self.assertRaises(HTTPException):main.bill_filter_reset()
        self.line.get_value.return_value=1
        self.assertIsNone(main.bill_filter_reset()['fault'])
        self.assertIsNone(self.journal.get_setting('bill_filter_fault'))
        self.assertEqual(self.journal.value(),1)
    def test_listener_publishes_only_complete_pulses_for_both_polarities(self):
        for active_low,stamp_format in product((True,False),('timespec','datetime')):
            with self.subTest(active_low=active_low,stamp_format=stamp_format):
                stop=threading.Event();line=Mock();line.get_value.return_value=1 if active_low else 0
                events=[]
                for i in range(10):
                    for active,stamp in [(True,1+i*.3),(False,1.1+i*.3)]:
                        falling=active if active_low else not active
                        events.append(SimpleNamespace(event_type=main.gpiod.line_event.FALLING_EDGE if falling else main.gpiod.line_event.RISING_EDGE,
                            timestamp=(datetime(1970,1,1)+timedelta(seconds=stamp) if stamp_format=='datetime' else SimpleNamespace(tv_sec=int(stamp),tv_nsec=round((stamp-int(stamp))*1e9)))))
                def wait(_):
                    if not events:stop.set();return False
                    return True
                line.event_wait.side_effect=wait;line.event_read.side_effect=lambda:events.pop(0)
                chip=Mock();chip.get_line.return_value=line
                self.journal.set_setting('bill_filter',{'active_low':active_low})
                before=self.journal.value()
                with patch.object(main.gpiod,'chip',return_value=chip),patch.object(main.time,'monotonic',side_effect=[0]+[100]*1000):
                    main.nv9_listener({'bill_acceptor':{'gpio_chip':'/dev/test','gpio_line':33}},self.journal,stop)
                self.assertEqual(self.journal.value()-before,10)
                line.release.assert_called_once()

    def test_wrong_initial_polarity_can_be_corrected_without_auto_clearing_fault(self):
        f=BillFilter({},True,0);f.poll(6)
        main.APP_STATE['bill_filter']=f;self.line.get_value.return_value=0
        response=main.bill_filter_write({'active_low':False})
        self.assertFalse(response['settings']['active_low'])
        self.assertFalse(response['active']);self.assertEqual(response['fault'],'stuck_active')
        self.assertEqual(self.journal.value(),0)

    def test_legacy_settings_gain_stuck_threshold_without_money_change(self):
        cfg={k:v for k,v in PRESETS['standard_50_100ms'].items() if k!='stuck_active_ms'}
        response=main.bill_filter_write(cfg)
        self.assertEqual(response['settings']['stuck_active_ms'],5000)
        self.assertEqual(self.journal.value(),0)

    def test_unknown_timestamp_latches_without_publishing(self):
        stop=threading.Event();line=Mock();line.get_value.return_value=1
        events=[SimpleNamespace(event_type=main.gpiod.line_event.FALLING_EDGE,timestamp=None)]
        def wait(_):
            if not events:stop.set();return False
            return True
        line.event_wait.side_effect=wait;line.event_read.side_effect=lambda:events.pop(0)
        chip=Mock();chip.get_line.return_value=line
        with patch.object(main.gpiod,'chip',return_value=chip),patch.object(main.time,'monotonic',return_value=1):
            main.nv9_listener({'bill_acceptor':{'gpio_chip':'/dev/test','gpio_line':33}},self.journal,stop)
        self.assertEqual(self.journal.value(),0)
        self.assertEqual(self.journal.get_setting('bill_filter_fault'),'timestamp_invalid')

    def test_level_monitor_has_no_journal_effect_and_rejects_overlap(self):
        before=self.journal.value()
        with patch.object(main.threading,'Thread') as thread:
            response=main.bill_level_trace_start({'seconds':180})
            self.assertFalse(response['credits_from_level_observer'])
            thread.return_value.start.assert_called_once()
            with self.assertRaises(HTTPException):main.bill_level_trace_start({'seconds':180})
        self.assertEqual(self.journal.value(),before)
        self.assertIn('levels',main.bill_trace_read())
    def test_level_monitor_rejects_bad_duration_or_unhealthy_input(self):
        for value in [{'seconds':True},{'seconds':301},{'seconds':9},{'gpio':11}]:
            with self.assertRaises(HTTPException):main.bill_level_trace_start(value)
        main.APP_STATE['bill_filter'].fault='stuck_active'
        with self.assertRaises(HTTPException):main.bill_level_trace_start({'seconds':10})

    def test_level_reader_publishes_50_complete_pulses_without_irq_and_preserves_journal(self):
        from bill_level_reader import LevelReader
        stop=threading.Event();line=Mock();line.get_value.return_value=1
        reader=LevelReader(line,True,False,0,20)
        for ms in range(1,8500):reader.observe(ms>=1000 and (ms-1000)%150<50,ms/1000)
        reader.start=Mock();original_read=reader.read
        def read():
            if not reader.pending():stop.set()
            return original_read()
        reader.read=read
        chip=Mock();chip.get_line.return_value=line
        before=self.journal.value();identity=self.journal.stream_id
        with patch.object(main.gpiod,'chip',return_value=chip),patch.object(main,'LevelReader',return_value=reader),patch.object(main.time,'monotonic',side_effect=[0]+[100]*1000):
            main.nv9_listener({'bill_acceptor':{'gpio_chip':'/dev/test','gpio_line':33,'reader':'level'}},self.journal,stop)
        self.assertEqual(self.journal.value()-before,50)
        self.assertEqual(self.journal.stream_id,identity)
        line.event_read.assert_not_called();line.event_wait.assert_not_called()
        self.assertEqual(line.request.call_args.args[0].request_type,main.gpiod.line_request.DIRECTION_INPUT)
        self.assertEqual(main.APP_STATE['bill_trace'].summary()['timestamp_source'],'sampled_monotonic')

class VendorListenerIntegrationTests(unittest.TestCase):
    def test_vendor_source_uses_existing_filter_and_durable_journal(self):
        from bill_level_reader import LevelReader
        with tempfile.TemporaryDirectory() as directory:
            journal=PulseJournal(str(Path(directory)/'counter.sqlite3'))
            old=dict(main.APP_STATE);stop=threading.Event()
            line=Mock();line.get_value.return_value=1
            reader=LevelReader(line,True,False,0,25)
            for ms in range(1,31000):
                reader.observe(ms>=1000 and (ms-1000)%150<50,ms/1000)
            reader.start=Mock();original=reader.read
            def read():
                if not reader.pending():stop.set()
                return original()
            reader.read=read
            try:
                main.APP_STATE['pulse_counter']=journal
                with patch.object(main,'VendorSysfsLine',return_value=line),patch.object(main,'VendorProcessLevelReader',return_value=reader),patch.object(main.gpiod,'chip') as gpiod,patch.object(main.time,'monotonic',side_effect=[0]+[100]*3000):
                    main.nv9_listener({'bill_acceptor':{'source':'vendor-sysfs','reader':'level-process'}},journal,stop)
                self.assertEqual(journal.value(),200)
                gpiod.assert_not_called();line.release.assert_called_once()
                journal.close();journal=PulseJournal(str(Path(directory)/'counter.sqlite3'))
                self.assertEqual(journal.value(),200)
            finally:
                journal.close();main.APP_STATE.clear();main.APP_STATE.update(old)
