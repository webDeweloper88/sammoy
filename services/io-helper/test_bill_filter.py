import unittest
from bill_filter import BillFilter,normalize,PRESETS

class BillFilterTests(unittest.TestCase):
    def make(self,**changes):
        f=BillFilter({**PRESETS['standard_50_100ms'],**changes},False,0)
        f.poll(.5);return f
    def pulse(self,f,start,width):
        self.assertFalse(f.edge(True,start))
        return f.edge(False,start+width)
    def test_measured_both_acceptors_and_large_bills_keep_every_pulse(self):
        for width,gap in [(.05,.1),(.1,.2)]:
            for count in [10,50,100,1000]:
                with self.subTest(width=width,count=count):
                    f=self.make()
                    for n in range(count):self.assertTrue(self.pulse(f,1+n*(width+gap),width))
                    self.assertEqual(f.accepted,count);self.assertFalse(f.fault)
    def test_no_credit_before_release_and_duplicate_notifications_do_not_double_count(self):
        f=self.make();self.assertFalse(f.edge(False,.6));self.assertFalse(f.edge(True,1))
        self.assertEqual(f.accepted,0)
        self.assertTrue(f.edge(False,1.05));self.assertFalse(f.edge(False,1.06))
        self.assertEqual(f.accepted,1)
    def test_short_glitches_and_short_gaps_are_rejected(self):
        f=self.make();self.assertFalse(self.pulse(f,1,.001));self.assertEqual(f.rejected['too_short'],1)
        self.assertFalse(self.pulse(f,1.005,.05));self.assertEqual(f.rejected['gap_too_short'],1)
        self.assertTrue(self.pulse(f,1.2,.05));self.assertEqual(f.accepted,1)
    def test_startup_requires_stable_inactive_input(self):
        f=BillFilter({},True,0)
        self.assertFalse(f.edge(False,.1));self.assertFalse(self.pulse(f,.2,.05))
        f.poll(.749);self.assertFalse(f.ready);f.poll(.75);self.assertTrue(f.ready)
        self.assertTrue(self.pulse(f,1,.05));self.assertEqual(f.accepted,1)
    def test_hung_input_faults_without_credit_and_requires_explicit_stable_reset(self):
        f=self.make();f.edge(True,1);f.poll(6.001)
        self.assertEqual(f.fault,'stuck_active');self.assertEqual(f.accepted,0)
        with self.assertRaises(ValueError):f.reset_fault(6.1)
        self.assertFalse(f.edge(False,6.1));self.assertFalse(self.pulse(f,7,.05))
        self.assertEqual(f.accepted,0)
        with self.assertRaises(ValueError):f.reset_fault(7.1)
        f.reset_fault(8);self.assertTrue(self.pulse(f,9,.05))
    def test_excessive_rate_is_latched_and_never_auto_resumes(self):
        f=self.make(max_pulses_per_second=2)
        self.assertTrue(self.pulse(f,1,.05));self.assertTrue(self.pulse(f,1.2,.05))
        self.assertFalse(self.pulse(f,1.4,.05));self.assertEqual(f.fault,'excessive_rate')
        self.assertFalse(self.pulse(f,10,.05));self.assertEqual(f.accepted,2)
        f.reset_fault(11);self.assertTrue(self.pulse(f,12,.05))
    def test_generic_supports_other_slow_pulses_without_model_assumption(self):
        f=BillFilter({'min_pulse_ms':100,'max_pulse_ms':3000,'min_gap_ms':100},False,0)
        f.poll(.5)
        for n in range(20):self.assertTrue(self.pulse(f,1+n*3,2))
    def test_fault_survives_reconstructed_filter_and_samples_are_bounded(self):
        f=BillFilter({},False,0,fault='excessive_rate');f.poll(5)
        self.assertFalse(self.pulse(f,6,.05));self.assertFalse(f.ready)
        f.reset_fault(7)
        for n in range(100):self.assertTrue(self.pulse(f,8+n,.05))
        self.assertEqual(len(f.snapshot()['samples']),32)
    def test_configuration_is_strict_and_detached(self):
        for bad in ({'bogus':0},{'min_pulse_ms':False},{'startup_idle_ms':0},{'max_pulse_ms':float('nan')},{'min_pulse_ms':500,'max_pulse_ms':100},{'active_low':1}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):normalize(bad)
        f=self.make();v=f.snapshot();v['settings']['min_pulse_ms']=10000
        self.assertEqual(f.settings['min_pulse_ms'],20)

    def test_completed_long_pulse_does_not_block_remaining_bill(self):
        f=self.make()
        self.assertFalse(self.pulse(f,1,.352))
        self.assertEqual(f.rejected['too_long'],1);self.assertIsNone(f.fault)
        for n in range(200):self.assertTrue(self.pulse(f,2+n*.15,.05))
        self.assertEqual(f.accepted,200)
        self.assertAlmostEqual(f.snapshot()['samples'][-1]['gap_ms'],100)
    def test_poll_during_rejected_long_pulse_does_not_latch_stuck(self):
        f=self.make();f.edge(True,1);f.poll(1.3)
        self.assertIsNone(f.fault);self.assertFalse(f.edge(False,1.352))
        self.assertTrue(self.pulse(f,1.5,.05))
    def test_missing_opposite_edge_is_diagnosed_without_inventing_credit(self):
        f=self.make();f.edge(True,1);f.edge(True,1.15)
        self.assertFalse(f.edge(False,1.201))
        self.assertEqual(f.rejected['edge_sequence'],1)
        self.assertEqual(f.snapshot()['repeated_edges'],1)
        self.assertIsNone(f.fault);self.assertTrue(self.pulse(f,1.3,.05))
    def test_backwards_clock_latches_and_never_credits(self):
        f=self.make();f.edge(True,1)
        self.assertFalse(f.edge(False,.9));self.assertEqual(f.fault,'timestamp_order')
        self.assertFalse(f.edge(False,1.05));self.assertEqual(f.accepted,0)
    def test_stuck_limit_is_separate_and_must_exceed_pulse_limit(self):
        self.assertEqual(normalize({'max_pulse_ms':250})['stuck_active_ms'],5000)
        with self.assertRaises(ValueError):normalize({'max_pulse_ms':5000})
        self.assertEqual(normalize({'max_pulse_ms':10000,'stuck_active_ms':20000})['stuck_active_ms'],20000)
