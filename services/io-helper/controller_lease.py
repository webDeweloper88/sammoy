"""Monotonic controller lease; diagnostic reads never renew permission."""
import threading
import time
from uuid import uuid4

class ControllerLease:
    def __init__(self,timeout_ms=2000,clock=time.monotonic):
        if not 500<=timeout_ms<=60000:raise ValueError('Watchdog must be 500–60000 ms')
        self.timeout=timeout_ms/1000;self.clock=clock;self.lock=threading.RLock()
        self.seen=None;self.boot_id=uuid4().hex;self.trip_seq=0;self.reason=None
    def heartbeat(self):
        with self.lock:self.seen=self.clock()
        return self.snapshot()
    def valid(self):
        with self.lock:return self.seen is not None and 0<=self.clock()-self.seen<self.timeout
    def trip(self,reason):
        with self.lock:
            if self.reason is None:self.trip_seq+=1
            self.reason=reason
    def rearm(self):
        with self.lock:self.reason=None
    def snapshot(self):
        with self.lock:return {'controller_boot_id':self.boot_id,'safety_trip_seq':self.trip_seq,'safety_reason':self.reason,'controller_lease_valid':self.valid()}
