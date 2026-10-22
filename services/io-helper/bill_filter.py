"""Configurable complete-pulse validation, independent of money denomination."""
from collections import Counter, deque
from copy import deepcopy

DEFAULTS = {'min_pulse_ms': 5, 'max_pulse_ms': 1000, 'min_gap_ms': 5,
            'startup_idle_ms': 500, 'max_pulses_per_second': 0, 'active_low': True,
            'stuck_active_ms': 5000}
PRESETS = {'generic': DEFAULTS,
           'standard_50_100ms': {**DEFAULTS, 'min_pulse_ms': 20, 'max_pulse_ms': 250,
                          'min_gap_ms': 20, 'max_pulses_per_second': 20}}


def normalize(value):
    if not isinstance(value, dict) or set(value)-set(DEFAULTS):
        raise ValueError('Unknown bill filter setting')
    result = {**DEFAULTS, **value}
    for key, low, high in [('min_pulse_ms',1,10000),('max_pulse_ms',1,10000),
                           ('min_gap_ms',0,10000),('startup_idle_ms',100,10000),
                           ('max_pulses_per_second',0,1000),('stuck_active_ms',100,60000)]:
        if type(result[key]) is not int or not low<=result[key]<=high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
    if (type(result['active_low']) is not bool
            or result['min_pulse_ms']>result['max_pulse_ms']
            or result['stuck_active_ms']<=result['max_pulse_ms']):
        raise ValueError('Invalid pulse polarity or duration range')
    return result


class BillFilter:
    def __init__(self, settings, active, now, fault=None):
        self.settings=normalize(settings)
        self.active=bool(active);self.inactive_since=None if active else now
        self.since=now if active else None
        self.previous_end=None;self.bad_gap=False;self.ready=False;self.fault=fault
        self.raw_edges=0;self.raw_pulses=0;self.accepted=0
        self.repeated_edges=0;self.last_edge_at=None;self.last_gap_ms=None
        self.uncertain_pulse=False;self.uncertain_reason=None
        self.rejected=Counter();self.samples=deque(maxlen=32);self.rate=deque()

    def poll(self, now):
        if self.active and self.since is not None and now-self.since>self.settings['stuck_active_ms']/1000:
            self.fault=self.fault or 'stuck_active'
        if not self.fault and not self.active and self.inactive_since is not None:
            if now-self.inactive_since+1e-9>=self.settings['startup_idle_ms']/1000:
                self.ready=True
        return self.ready and not self.fault

    def edge(self, active, now):
        active=bool(active);self.raw_edges+=1
        if self.last_edge_at is not None and now < self.last_edge_at:
            self.fault=self.fault or 'timestamp_order'
            self.rejected['timestamp_order']+=1
            return False
        self.last_edge_at=now
        if active==self.active:
            self.repeated_edges+=1
            if active:self.uncertain_pulse=True;self.uncertain_reason='edge_sequence'
            return False  # A missing opposite edge must never synthesize money.
        # A first pulse after an observed stable idle can start before poll().
        self.poll(now)
        self.active=active
        if active:
            self.raw_pulses+=1
            self.since=now;self.inactive_since=None;self.uncertain_pulse=False;self.uncertain_reason=None
            self.last_gap_ms=None if self.previous_end is None else (now-self.previous_end)*1000
            self.bad_gap=self.last_gap_ms is not None and self.last_gap_ms+1e-6<self.settings['min_gap_ms']
            if not self.ready and not self.fault:self.rejected['startup']+=1
            return False
        self.inactive_since=now;self.previous_end=now
        if self.since is None:return False
        width=(now-self.since)*1000;self.since=None
        if self.fault:reason='fault'
        elif not self.ready:reason=None  # Counted once at its starting edge.
        elif self.uncertain_pulse:reason=self.uncertain_reason or 'edge_sequence'
        elif width+1e-6<self.settings['min_pulse_ms']:reason='too_short'
        elif width-1e-6>self.settings['max_pulse_ms']:reason='too_long'
        elif self.bad_gap:reason='gap_too_short'
        else:
            while self.rate and now-self.rate[0]>=1:self.rate.popleft()
            limit=self.settings['max_pulses_per_second']
            if limit and len(self.rate)>=limit:
                self.fault='excessive_rate';reason='excessive_rate'
            else:
                self.rate.append(now);self.accepted+=1;reason=None
                self.samples.append({'width_ms':round(width,3),'gap_ms':None if self.last_gap_ms is None else round(self.last_gap_ms,3),'accepted':True})
                return True
        if reason:self.rejected[reason]+=1
        self.samples.append({'width_ms':round(width,3),'gap_ms':None if self.last_gap_ms is None else round(self.last_gap_ms,3),'accepted':False,'reason':reason or 'startup'})
        return False

    def can_reset(self, now):
        return not self.active and self.inactive_since is not None and now-self.inactive_since+1e-9>=self.settings['startup_idle_ms']/1000

    def reset_fault(self, now):
        if not self.can_reset(now):raise ValueError('Input must be stably inactive before reset')
        self.fault=None;self.ready=True;self.since=None;self.rate.clear()

    def snapshot(self):
        return {'settings':deepcopy(self.settings),'ready':bool(self.ready and not self.fault),
                'active':self.active,'fault':self.fault,'raw_edges':self.raw_edges,
                'raw_pulses':self.raw_pulses,'validated_pulses':self.accepted,
                'repeated_edges':self.repeated_edges,
                'rejected':dict(self.rejected),'samples':list(self.samples)}
