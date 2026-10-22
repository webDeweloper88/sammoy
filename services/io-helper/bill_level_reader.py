"""Optional GPIO level reader for boards that lose both-edge IRQ events.

Only observed transitions are queued. No inferred or reconstructed pulses.
The sampling thread never writes the cash journal or waits for its lock.
"""
from dataclasses import dataclass
from queue import Queue, Empty, Full
import threading
import time


@dataclass(frozen=True)
class LevelEvent:
    active: bool
    at: float
    changed: bool
    uncertain: bool


class LevelReader:
    def __init__(self, line, active_low, initial_active, initial_at, gap_limit_ms):
        self.line=line;self.active_low=active_low
        self.previous=initial_active;self.last_at=initial_at
        self.gap_limit_ms=gap_limit_ms
        self.queue=Queue(maxsize=4096)
        self.available=threading.Event();self.state_lock=threading.RLock()
        self.stop=threading.Event();self.thread=None
        self.error=None;self.samples=0;self.max_gap_ms=0;self.gaps=0

    def observe(self, active, at):
        with self.state_lock:self._observe(active,at)

    def _observe(self, active, at):
        gap=(at-self.last_at)*1000
        if gap<0:
            self.error='timestamp_order';return
        self.samples+=1;self.max_gap_ms=max(self.max_gap_ms,gap)
        uncertain=gap>self.gap_limit_ms
        if uncertain:self.gaps+=1
        changed=active!=self.previous
        if changed or uncertain:
            try:
                self.queue.put_nowait(LevelEvent(active,at,changed,uncertain))
                self.available.set()
            except Full:self.error='reader_overflow'
        self.previous=active;self.last_at=at

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='bill-level-reader')
        self.thread.start()

    def run(self):
        try:
            while not self.stop.is_set() and not self.error:
                with self.state_lock:
                    value=self.line.get_value()
                    if value not in (0,1):raise ValueError('Invalid GPIO level')
                    self._observe(value==0 if self.active_low else value!=0,time.monotonic())
                self.stop.wait(.002)
        except Exception:
            self.error='reader_failed'

    def read(self):
        try:return self.queue.get_nowait()
        except Empty:return None
        finally:
            if self.queue.empty():self.available.clear()

    def pending(self):return not self.queue.empty()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=1)

    def snapshot(self):
        return {'reader':'level','samples':self.samples,'max_sample_gap_ms':round(self.max_gap_ms,3),
                'uncertain_gaps':self.gaps,'reader_error':self.error,
                'queued_transitions':self.queue.qsize()}
