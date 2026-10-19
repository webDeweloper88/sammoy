"""Short-lived metadata proofs, isolated to one synchronous card operation.

Never cache card state, balances, commands, or financial responses. The receiver
still checks current authority and replicates every money operation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import logging
import time

_scope = ContextVar('wallet_card_operation', default=None)
_log = logging.getLogger('uvicorn.error.wallet')
PROOF_TTL_SECONDS = 2.0


@contextmanager
def card_operation():
    if _scope.get() is not None:
        yield
        return
    scope = {'proofs': {}, 'calls': {}, 'hits': 0}
    token = _scope.set(scope)
    started = time.monotonic()
    try:
        yield
    finally:
        _scope.reset(token)
        _log.info('wallet_card_timing total_ms=%s proof_reuse=%s rpc=%s',
                  round((time.monotonic()-started)*1000), scope['hits'], scope['calls'])


def status_proof(cfg, post):
    from .wallet_api import rpc
    scope = _scope.get()
    key = tuple(cfg.get(k) for k in ('site_id', 'local_post', 'primary_post',
                'standby_post', 'generation', 'single_node')) + (post, cfg.get('peer_urls', {}).get(str(post)))
    if scope is not None:
        cached = scope['proofs'].get(key)
        if cached is not None and time.monotonic()-cached[0] < PROOF_TTL_SECONDS:
            scope['hits'] += 1
            return deepcopy(cached[1])
    proof = rpc(cfg, post, 'status', {})
    if scope is not None:
        scope['proofs'][key] = (time.monotonic(), deepcopy(proof))
    return proof


def timed_rpc(function):
    @wraps(function)
    def call(cfg, post, action, payload):
        started = time.monotonic()
        try:
            return function(cfg, post, action, payload)
        finally:
            scope = _scope.get()
            if scope is not None:
                key = str(post)+':'+action
                row = scope['calls'].setdefault(key, {'count': 0, 'ms': 0})
                row['count'] += 1
                row['ms'] += round((time.monotonic()-started)*1000)
    return call
