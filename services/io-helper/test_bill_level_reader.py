import threading,unittest
from queue import Queue
from unittest.mock import Mock,patch
from bill_level_reader import LevelReader
from bill_filter import BillFilter,PRESETS


class LevelReaderTests(unittest.TestCase):
    def reader(self,**kw):
        return LevelReader(Mock(),kw.get('active_low',True),False,0,20)
    def consume(self,f,reader):
        while reader.pending():
            event=reader.read()
            if event.uncertain and f.active:f.uncertain_pulse=True;f.uncertain_reason='sampling_gap'
            accepted=f.edge(event.active,event.at) if event.changed else False
            if event.uncertain and event.active:f.uncertain_pulse=True;f.uncertain_reason='sampling_gap'
        return f.accepted
    def test_full_200_pulse_bill_survives_delayed_consumer(self):
        r=self.reader();f=BillFilter(PRESETS['standard_50_100ms'],False,0);f.poll(.5)
        # Sampler continues capturing while the consumer could be fsyncing.
        for ms in range(1,31001):
            active=ms>=1000 and (ms-1000)%150<50
            r.observe(active,ms/1000)
        self.assertEqual(self.consume(f,r),200)
        self.assertIsNone(f.fault);self.assertEqual(r.gaps,0)
    def test_oversleep_does_not_invent_a_completed_pulse(self):
        r=self.reader();f=BillFilter(PRESETS['standard_50_100ms'],False,0);f.poll(.5)
        r.last_at=.999;r.observe(True,1)
        r.observe(False,1.05)  # 50ms observation gap: ownership of width is uncertain.
        self.assertEqual(self.consume(f,r),0)
        self.assertEqual(f.rejected['sampling_gap'],1)
    def test_queue_overflow_latches_reader_failure(self):
        r=self.reader();r.queue=Queue(maxsize=1)
        r.observe(True,.001);r.observe(False,.002)
        self.assertEqual(r.error,'reader_overflow')
    def test_backwards_clock_and_sampling_exception_fail_closed(self):
        r=self.reader();r.observe(False,-1);self.assertEqual(r.error,'timestamp_order')
        r=self.reader();r.line.get_value.side_effect=OSError('disconnected');r.run()
        self.assertEqual(r.error,'reader_failed');self.assertFalse(r.pending())
    def test_sampler_never_touches_journal_or_outputs_and_both_polarities_work(self):
        for low in (True,False):
            r=self.reader(active_low=low)
            r.line.get_value.side_effect=[0 if low else 1,1 if low else 0]
            def wait(_):
                if r.samples==2:r.stop.set()
            with patch.object(r.stop,'wait',side_effect=wait),patch('bill_level_reader.time.monotonic',side_effect=[.001,.002]):r.run()
            self.assertEqual([r.read().active,r.read().active],[True,False])
            self.assertEqual([call[0] for call in r.line.method_calls],['get_value','get_value'])
