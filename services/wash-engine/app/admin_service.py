"""Admin operations on the existing runtime; no alternative wash state machine."""
import httpx
from fastapi import HTTPException

OUTPUTS = ('water', 'osmos', 'nano', 'foam', 'wax', 'chem', 'vacuum', 'air')

def require_idle(runtime):
    state = runtime.snapshot()['state']
    if (state.get('activeMode') or state.get('requestedOutput') or state.get('armedMode')
            or int(state.get('creditSum') or 0) > 0 or state.get('activeSessionId')
            or int(state.get('vipRemainingSeconds') or 0) > 0):
        raise HTTPException(409, 'Сначала завершите текущий сеанс. Баланс и время клиента сохраняются.')

def io_sync(client, base, path, payload=None):
    try:
        response = client.get(base+path) if payload is None else client.post(base+path, json=payload)
        data = response.json()
        if response.status_code >= 400:
            raise HTTPException(response.status_code, data.get('detail', 'I/O command failed'))
        return data
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Нет подтверждённого ответа от контроллера I/O') from None

def test_relay(runtime, base, name, confirmed, client_factory=httpx.Client):
    if name not in OUTPUTS: raise HTTPException(404, 'Unknown output')
    if confirmed != name: raise HTTPException(400, 'Подтвердите выбранный выход')
    # tick(), customer mode changes and this test serialize on the same existing lock.
    # The helper itself owns the timed OFF, even if the browser or engine disconnects.
    with runtime.lock:
        require_idle(runtime)
        with client_factory(timeout=8) as client:
            io = io_sync(client, base, '/io')
            if not io.get('modbus_ok') or any(io.get('outputs', {}).get(output, True) for output in OUTPUTS):
                raise HTTPException(409, 'Для теста нужна связь Modbus и все выходы OFF')
            try:
                result = io_sync(client, base, f'/outputs/{name}/test', {})
            finally:
                runtime.last_output = None
                io_sync(client, base, f'/outputs/{name}', {'on': False})
            verified = io_sync(client, base, '/io')
            if not verified.get('modbus_ok') or any(verified.get('outputs', {}).get(output, True) for output in OUTPUTS):
                raise HTTPException(503, 'Выключение после теста не подтверждено')
            return result

def all_off(runtime, base, client_factory=httpx.Client):
    with runtime.lock:
        # Use the established WEB PAUSE behavior, including trigger-reset interlock.
        # An I/O error here must not prevent attempts to switch off the other relays.
        try: runtime.select_mode('pause')
        except Exception: pass
        errors=[]
        with client_factory(timeout=3) as client:
            for name in OUTPUTS:
                try: io_sync(client,base,f'/outputs/{name}',{'on':False})
                except HTTPException: errors.append(name)
            runtime.last_output=None
            io=io_sync(client,base,'/io')
        if errors or not io.get('modbus_ok') or any(io.get('outputs',{}).get(name,True) for name in OUTPUTS):
            raise HTTPException(503,'Не все выходы подтвердили OFF. Проверьте контроллер и аварийное отключение.')
        return {'ok':True,'outputs':io['outputs'],'state':runtime.snapshot()['state']}
