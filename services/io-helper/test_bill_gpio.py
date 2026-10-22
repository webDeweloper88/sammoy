from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import unittest
from bill_gpio import event_seconds,BillGPIOTrace
from bill_filter import BillFilter,PRESETS

class BillGPIOTests(unittest.TestCase):
    def test_installed_pypi_datetime_binding_uses_uptime_without_local_timezone(self):
        for stamp in [1.05,123456.123456,864001.5]:
            event=SimpleNamespace(timestamp=datetime(1970,1,1)+timedelta(seconds=stamp))
            self.assertAlmostEqual(event_seconds(event),stamp,places=6)
    def test_timespec_binding(self):
        self.assertAlmostEqual(event_seconds(SimpleNamespace(timestamp=SimpleNamespace(tv_sec=123,tv_nsec=50000000))),123.05)
    def test_no_fallback_for_unknown_clock(self):
        for stamp in [None,1,datetime(2026,1,1,tzinfo=timezone.utc),SimpleNamespace(tv_sec=1,tv_nsec=-1)]:
            with self.assertRaises(ValueError):event_seconds(SimpleNamespace(timestamp=stamp))
    def test_delayed_processing_keeps_all_200_pulses_at_kernel_width(self):
        f=BillFilter(PRESETS['standard_50_100ms'],False,0)
        trace=BillGPIOTrace()
        for n in range(200):
            for active,stamp in [(True,1+n*.15),(False,1.05+n*.15)]:
                event=SimpleNamespace(timestamp=datetime(1970,1,1)+timedelta(seconds=stamp))
                at=event_seconds(event);accepted=f.edge(active,at)
                row=trace.record(kernel_at=at,read_at=stamp+2,active=active,accepted=accepted,fault=f.fault,repeated=False)
                if accepted:trace.committed(row,.4)
        self.assertEqual(f.accepted,200);self.assertIsNone(f.fault)
        self.assertAlmostEqual(f.samples[-1]['width_ms'],50)
        self.assertEqual(trace.summary()['events_observed'],400)
        self.assertEqual(trace.summary()['max_queue_delay_ms'],2000)
        self.assertEqual(trace.summary()['max_commit_ms'],400)
    def test_trace_bounded_and_snapshot_detached(self):
        trace=BillGPIOTrace()
        for n in range(3000):trace.record(kernel_at=n,read_at=n,active=False,accepted=False,fault=None,repeated=False)
        self.assertEqual(len(trace.snapshot()['events']),2048)
        snapshot=trace.snapshot();snapshot['events'][0]['active']=True
        self.assertFalse(trace.snapshot()['events'][0]['active'])

class BillLevelTraceTests(unittest.TestCase):
    def test_independent_observation_counts_levels_without_inventing_credit(self):
        from bill_gpio import BillLevelTrace
        trace=BillLevelTrace(180,0)
        for active,now in [(False,0),(False,.005),(True,.01),(True,.015),(False,.06)]:trace.observe(active,now)
        s=trace.snapshot()
        self.assertEqual(s['samples'],5)
        self.assertEqual([r['active'] for r in s['transitions']],[False,True,False])
        self.assertEqual(s['max_sample_gap_ms'],45)
        s['transitions'][0]['active']=True
        self.assertFalse(trace.snapshot()['transitions'][0]['active'])
