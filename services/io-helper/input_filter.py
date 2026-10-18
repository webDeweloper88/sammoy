"""Debounce active edges without delaying release of a wash trigger."""
import math

class InputFilter:
    def __init__(self, debounce_ms=0):
        if isinstance(debounce_ms,bool) or not isinstance(debounce_ms,(int,float)) or not math.isfinite(debounce_ms) or not 0<=debounce_ms<=5000:
            raise ValueError('debounce_ms must be between 0 and 5000')
        self.delay=debounce_ms/1000
        self.reset()

    def reset(self):
        self.active=False
        self.since=None

    def observe(self,active,now):
        if not active:
            self.reset()
            return False
        if self.active:return True
        if self.since is None:self.since=now
        if now-self.since+1e-9>=self.delay:self.active=True
        return self.active
