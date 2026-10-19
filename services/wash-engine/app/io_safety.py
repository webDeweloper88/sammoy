"""Validate native Radxa I/O proof before billing or requesting outputs."""
import math
from datetime import datetime,UTC
from .device_profiles import profile

OUTPUTS=('water','osmos','nano','foam','wax','chem','vacuum','air')

def validate_io(io,last_output=None,device_type="wash"):
    expected=profile(device_type)['outputs']
    if last_output is not None and last_output not in expected:raise RuntimeError('Unknown confirmed output')
    if not isinstance(io,dict):raise RuntimeError('Invalid I/O response')
    if io.get('device_type','wash')!=device_type:raise RuntimeError('Hardware device profile mismatch')
    # Legacy list-shaped responses remain supported; native Radxa proof is strict.
    if device_type=='dry_fog' and not isinstance(io.get('inputs'),dict):raise RuntimeError('Dry fog requires native I/O proof')
    if not isinstance(io.get('inputs'),dict):
        if io.get('modbus_ok') is False:raise RuntimeError('Modbus is unavailable')
        return
    if io.get('nv9_enabled') is not False and io.get('nv9_listener_alive') is False:raise RuntimeError('NV9 listener is not running')
    if io.get('modbus_ok') is not True:raise RuntimeError('Modbus is unavailable')
    age=io.get('poll_age_seconds')
    if age is None:
        try:age=(datetime.now(UTC)-datetime.fromisoformat(io['last_poll_at'])).total_seconds()
        except (KeyError,ValueError,TypeError):raise RuntimeError('I/O freshness is unknown') from None
    if isinstance(age,bool) or not isinstance(age,(int,float)) or not math.isfinite(age) or not 0<=age<2:
        raise RuntimeError('I/O polling is stale')
    outputs=io.get('outputs')
    if not isinstance(outputs,dict) or any(type(outputs.get(n)) is not bool for n in expected) or (device_type=='dry_fog' and set(outputs)!=set(expected)):
        raise RuntimeError('Output readback is incomplete')
    active=[n for n in expected if outputs[n]]
    if active != ([last_output] if last_output else []):
        raise RuntimeError('Output readback differs from the confirmed mode')
