"""Decode the kernel clock used by supported libgpiod 1.x bindings.

The PyPI 1.5.4 binding encodes monotonic uptime as a naive datetime since
1970, not a wall-clock timestamp. Never replace it with read/processing time.
"""
from datetime import datetime
import math


def event_seconds(event):
    stamp = event.timestamp
    if isinstance(stamp, datetime):
        if stamp.tzinfo is not None:
            raise ValueError('Unexpected timezone in GPIO kernel timestamp')
        seconds = (stamp - datetime(1970, 1, 1)).total_seconds()
    elif hasattr(stamp, 'tv_sec') and hasattr(stamp, 'tv_nsec'):
        if not 0 <= stamp.tv_nsec < 1_000_000_000:
            raise ValueError('Invalid GPIO timestamp nanoseconds')
        seconds = float(stamp.tv_sec) + float(stamp.tv_nsec) / 1e9
    else:
        raise ValueError('Unsupported GPIO kernel timestamp; credit stopped')
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid GPIO kernel timestamp')
    return seconds


class BillGPIOTrace:
    """Bounded RAM trace; polling it never writes the money journal."""
    def __init__(self):
        from collections import deque
        self.events = deque(maxlen=2048)
        self.timestamp_source='kernel'
        self.total_events = 0
        self.max_queue_delay_ms = 0
        self.max_commit_ms = 0

    def record(self, *, kernel_at, read_at, active, accepted, fault, repeated):
        self.total_events += 1
        delay = max(0, (read_at-kernel_at)*1000)
        self.max_queue_delay_ms = max(self.max_queue_delay_ms, delay)
        row = {'sequence':self.total_events, 'kernel_seconds':round(kernel_at,6),
               'read_seconds':round(read_at,6), 'queue_delay_ms':round(delay,3),
               'active':active, 'accepted':accepted, 'fault':fault, 'repeated':repeated}
        self.events.append(row)
        return row

    def committed(self, row, elapsed):
        value=max(0,elapsed*1000)
        row['commit_ms']=round(value,3)
        self.max_commit_ms=max(self.max_commit_ms,value)

    def summary(self):
        return {'timestamp_source':self.timestamp_source, 'events_observed':self.total_events,
                'trace_capacity':self.events.maxlen,
                'max_queue_delay_ms':round(self.max_queue_delay_ms,3),
                'max_commit_ms':round(self.max_commit_ms,3)}

    def snapshot(self):
        return {**self.summary(),'events':[dict(row) for row in self.events]}


class BillLevelTrace:
    """Temporary independent level observation. Never feeds the cash filter."""
    def __init__(self, duration_seconds, now):
        import threading
        from collections import deque
        self.lock = threading.Lock()
        self.ends_at = now+duration_seconds
        self.transitions = deque(maxlen=2048)
        self.samples = 0
        self.last_at = None
        self.last_active = None
        self.max_gap_ms = 0
        self.error = None
        self.finished = False

    def observe(self, active, now):
        with self.lock:
            if self.last_at is not None:
                self.max_gap_ms=max(self.max_gap_ms,(now-self.last_at)*1000)
            self.last_at=now
            self.samples+=1
            if self.last_active is None or self.last_active!=active:
                self.transitions.append({'sample':self.samples,'seconds':round(now,6),'active':active})
            self.last_active=active

    def snapshot(self):
        with self.lock:
            return {'samples':self.samples,'max_sample_gap_ms':round(self.max_gap_ms,3),
                    'finished':self.finished,'error':self.error,'ends_at':self.ends_at,
                    'transitions':[dict(row) for row in self.transitions]}
