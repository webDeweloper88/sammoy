"""Short-lived runtime interlock acquired by the local root installer."""
import time

def blocked(runtime):
    deadline=runtime.state.get('softwareUpdatePendingUntil',0)
    if deadline and time.monotonic()<deadline:return True
    runtime.state.pop('softwareUpdatePendingUntil',None)
    runtime.state.pop('softwareUpdateJob',None)
    return False
