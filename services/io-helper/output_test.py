"""Finite relay test independent of the requesting browser/engine connection."""
import threading
import time

class OutputTest:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = None

    def run(self, controller, name, refresh, wait=time.sleep):
        with self.lock:
            if self.active is not None:
                raise ValueError('An output test is already running')
            if any(controller.read_outputs()):
                raise ValueError('Switch every output off before testing')
            self.active = name
            try:
                controller.write_output(name, True)
                refresh(controller)
            except Exception:
                try: controller.write_output(name, False)
                finally: self.active = None
                raise
        try:
            wait(1.0)
        finally:
            try:
                controller.write_output(name, False)
                refresh(controller)
            finally:
                with self.lock:
                    self.active = None
        return {'ok': True, 'output': name, 'duration_ms': 1000, 'actual': False}
