"""Reusable synchronous transports, without caching replies or retrying commands."""
import atexit
from contextlib import contextmanager
import threading
import httpx

_lock=threading.Lock()
_clients={}

@contextmanager
def sync_client(*,scope,timeout):
    key=(scope,float(timeout))
    with _lock:
        client=_clients.get(key)
        if client is None or client.is_closed:
            # Client supports concurrent requests. Keep wallet and I/O pools
            # separate so slow peer requests cannot exhaust the safety channel.
            client=httpx.Client(timeout=timeout,trust_env=False,
                limits=httpx.Limits(max_connections=32,max_keepalive_connections=16,keepalive_expiry=15))
            _clients[key]=client
    yield client

def close_all():
    with _lock:
        clients=list(_clients.values());_clients.clear()
    for client in clients:client.close()

atexit.register(close_all)
