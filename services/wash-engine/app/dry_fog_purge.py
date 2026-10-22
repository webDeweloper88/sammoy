"""Idle-only relay 8 maintenance. Call with the runtime lock held."""
import time
from math import ceil


def normalize(value):
    if not isinstance(value, dict):
        raise ValueError('Purge settings must be an object')
    result = {'enabled': False, 'idleSeconds': 7200, 'durationSeconds': 30, **value}
    if type(result['enabled']) is not bool:
        raise ValueError('Purge enabled must be boolean')
    for key, low, high in [('idleSeconds', 60, 604800), ('durationSeconds', 1, 300)]:
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f'Purge {key} must be between {low} and {high}')
    return {key: result[key] for key in ('enabled', 'idleSeconds', 'durationSeconds')}


def cancel(runtime):
    if getattr(runtime, 'device_type', 'wash') != 'dry_fog':
        return
    runtime._purge_idle_since = time.monotonic()
    runtime._purge_until = None
    runtime.state['purgeActive'] = False
    runtime.state['purgeRemainingSeconds'] = 0
    if runtime.last_output == 'purge':
        runtime._apply_output_sync(None)
        runtime.state['requestedOutput'] = None


def requested(runtime, now):
    if getattr(runtime, 'device_type', 'wash') != 'dry_fog':
        return None
    config = runtime.params['purge']
    state = runtime.state
    busy = (state.get('creditSum', 0) > 0 or runtime.active_session_id
            or state.get('walletTransferPending') or state.get('walletCashHeld', 0) > 0
            or state.get('powerRecoveryAvailable') or state.get('licenseLocked')
            or state.get('deviceProfileMismatch') or state.get('lastError')
            or state.get('lastIoOk') is not True or state.get('armedMode')
            or state.get('activeMode') or getattr(runtime, '_click_credit_pending', None))
    if busy or not config['enabled']:
        cancel(runtime)
        return None
    if runtime._purge_until is not None and now >= runtime._purge_until:
        cancel(runtime)
        return None
    if runtime._purge_until is None:
        if now - runtime._purge_idle_since < config['idleSeconds']:
            return None
        runtime._purge_until = now + config['durationSeconds']
    state['purgeActive'] = True
    state['purgeRemainingSeconds'] = max(0, ceil(runtime._purge_until-now))
    return 'purge'
