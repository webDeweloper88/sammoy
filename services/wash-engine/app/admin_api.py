from datetime import datetime, UTC
from uuid import UUID
import asyncio
import os
from pathlib import Path
import shutil
from typing import Annotated, Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb
from .auth import require_role
from .config import settings
from .db import db
from .io_client import io_request
from .wash_logic import wash_runtime
from .admin_service import all_off, test_relay, require_idle

router=APIRouter(prefix='/api/admin')
Admin=Annotated[dict,Depends(require_role('admin'))]

def audit(user,action,message):
    with db() as conn:
        conn.execute("INSERT INTO system_events(level,event_type,source,message,context) VALUES('info',%s,'admin-ui',%s,%s)",
                     (action,message,Jsonb({'changed_by':user['login']})))
        conn.commit()

@router.get('/diagnostics')
async def diagnostics(user:Admin):
    async def fetch(path):
        try:return {'available':True,'data':await io_request(path)}
        except HTTPException as e:return {'available':False,'error':e.detail}
    health,io,rfid,config=await asyncio.gather(*(fetch(p) for p in ('/health','/io','/rfid/latest','/configuration')))
    root=Path(settings.kiosk_assets_dir);root.mkdir(parents=True,exist_ok=True)
    disk=shutil.disk_usage(root)
    temperature=None
    for path in sorted(Path('/host-sys/class/thermal').glob('thermal_zone*/temp')):
        try:temperature=round(int(path.read_text())/1000,1);break
        except (ValueError,OSError):pass
    snapshot=wash_runtime.snapshot()
    return {'ok':True,'checked_at':datetime.now(UTC).isoformat(),'health':health,'io':io,'rfid':rfid,'configuration':config,
            'state':snapshot['state'],'simulation':snapshot['simulation'],
            'parameters':{'billPulseSum':snapshot['parameters']['billPulseSum']},
            'system':{'load_1m':os.getloadavg()[0],'temperature_c':temperature,'disk_free_bytes':disk.free,'disk_total_bytes':disk.total}}

class RelayTestRequest(BaseModel): confirmation:str
@router.post('/service/outputs/{name}/test')
def output_test(name:str,payload:RelayTestRequest,user:Admin):
    result=test_relay(wash_runtime,settings.io_helper_url,name,payload.confirmation)
    audit(user,'admin_output_test',f'{name}: 1 second test, OFF confirmed')
    return result

@router.post('/service/all-off')
def outputs_off(user:Admin):
    result=all_off(wash_runtime,settings.io_helper_url)
    audit(user,'admin_all_off','WEB PAUSE applied; all eight outputs confirmed OFF')
    return result

class MoneyInputRequest(BaseModel): bill_pulse_sum:int=Field(ge=1,le=10_000_000)
@router.post('/service/money-input')
def money_input(payload:MoneyInputRequest,user:Admin):
    with wash_runtime.lock:
        require_idle(wash_runtime)
        parameters=wash_runtime.snapshot()['parameters']
        parameters['billPulseSum']=payload.bill_pulse_sum
        result=wash_runtime.save_parameters(parameters)
    audit(user,'admin_bill_pulse_value','Bill pulse value updated')
    return {'ok':True,'parameters':result}

@router.post('/service/real-inputs')
def real_inputs(user:Admin):
    from .main import apply_license_to_runtime
    with wash_runtime.lock:
        require_idle(wash_runtime)
        wash_runtime.reset_simulation()
        apply_license_to_runtime()
    audit(user,'admin_simulation_reset','Real hardware inputs restored')
    return wash_runtime.snapshot()

@router.get('/service/events')
def events(user:Admin,level:Literal['all','info','warning','error','critical']='all',before:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
    with db() as conn:
        rows=conn.execute("""SELECT id,created_at,level,event_type,source,message FROM system_events
            WHERE (%s='all' OR level=%s) AND (%s=0 OR id<%s) ORDER BY id DESC LIMIT %s""",(level,level,before,before,limit+1)).fetchall()
    return {'ok':True,'events':rows[:limit],'has_more':len(rows)>limit}

@router.get('/service/recovery')
def recovery(user:Admin):
    with db() as conn:
        rows=conn.execute("SELECT id,wash_session_id,amount_sum,status,created_at FROM recovery_credits WHERE status='unclaimed' ORDER BY id DESC LIMIT 100").fetchall()
    return {'ok':True,'credits':rows}

async def network_request(path,method='GET',payload=None):
    socket=os.environ.get('ADMIN_NETWORK_SOCKET','/run/sammoy2-admin/network.sock')
    try:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket),timeout=40) as client:
            response=await client.request(method,'http://localhost'+path,json=payload if method=='POST' else None)
            data=response.json()
    except (httpx.HTTPError,ValueError):raise HTTPException(503,'Служба настройки сети недоступна') from None
    if response.status_code>=400:raise HTTPException(response.status_code,data.get('detail','Network configuration failed'))
    return data

@router.get('/network/status')
async def network_status(user:Admin):return await network_request('/status')
@router.get('/network/wifi')
async def network_wifi(user:Admin):return await network_request('/wifi')
@router.post('/network/{action}')
async def network_action(action:Literal['apply','confirm','rollback','temporary-disconnect'],payload:dict,user:Admin):
    if action in ('apply','temporary-disconnect'):require_idle(wash_runtime)
    result=await network_request('/'+action,'POST',payload)
    audit(user,'admin_network_'+action,'Network '+action+' requested')
    return result

@router.get('/service/storage')
def storage(user:Admin):
    from .retention import EVENT_MONTHS, FINANCIAL_MONTHS
    disk=shutil.disk_usage(settings.kiosk_assets_dir)
    free_percent=round(disk.free/disk.total*100,1)
    level='critical' if disk.free<1024**3 or free_percent<5 else 'warning' if disk.free<2*1024**3 or free_percent<10 else 'ok'
    with db() as conn:
        conn.execute("SET LOCAL statement_timeout='3s'")
        size=conn.execute('SELECT pg_database_size(current_database()) AS bytes').fetchone()['bytes']
        events=conn.execute('SELECT count(*) AS count,min(created_at) AS oldest FROM system_events').fetchone()
        status=conn.execute("SELECT setting_value FROM app_settings WHERE setting_key='retention_status'").fetchone()
        protected=conn.execute("SELECT count(*) AS count,coalesce(sum(amount_sum),0) AS amount_sum FROM recovery_credits WHERE status='unclaimed'").fetchone()
    return {'ok':True,'disk_total_bytes':disk.total,'disk_free_bytes':disk.free,'free_percent':free_percent,
        'database_bytes':size,'level':level,'events':events,'protected_credit':protected,
        'retention':{'event_months':EVENT_MONTHS,'financial_months':FINANCIAL_MONTHS,'journal_limit_mb':256,
                     'last_run':status['setting_value'] if status else None}}

from uuid import UUID
@router.get('/service/click-payments')
def click_payments(user:Admin,
    status:Literal['all','local_pending','pending','prepared','paid','credited','cancelled','expired','error']='all',
    before_time:datetime|None=None,before_id:UUID|None=None,limit:int=Query(30,ge=1,le=100)):
    from .main import serialize_click_intent
    if (before_time is None)!=(before_id is None):raise HTTPException(422,'Both cursor fields are required')
    with db() as conn:
        conn.execute("SET LOCAL statement_timeout='3s'")
        rows=conn.execute("""SELECT * FROM click_payment_intents
            WHERE (%s='all' OR status=%s)
            AND (%s::timestamptz IS NULL OR (created_at,id)<(%s::timestamptz,%s::uuid))
            ORDER BY created_at DESC,id DESC LIMIT %s""",(status,status,before_time,before_time,before_id,limit+1)).fetchall()
        summary=conn.execute("""SELECT status,count(*) AS count,coalesce(sum(amount_sum),0) AS amount_sum
            FROM click_payment_intents GROUP BY status""").fetchall()
    page=rows[:limit]
    return {'ok':True,'intents':[serialize_click_intent(r) for r in page],'summary':summary,'has_more':len(rows)>limit,
        'next_cursor':{'before_time':page[-1]['created_at'].isoformat(),'before_id':str(page[-1]['id'])} if len(rows)>limit else None}


class TestCreditRequest(BaseModel):
    amount_sum: int = Field(strict=True, ge=1, le=100_000)
    operation_id: UUID
    reason: str = Field(min_length=5, max_length=200)
    confirmation: str


@router.post('/service/test-credit')
def test_credit(payload: TestCreditRequest, user: Admin):
    """Audited bench credit: not a cash pulse or a Click payment."""
    if payload.confirmation != f'TEST CREDIT {payload.amount_sum}':
        raise HTTPException(422, 'Подтвердите сумму тестового начисления')
    key='admin-test:'+str(payload.operation_id)
    with wash_runtime.lock:
        with db() as conn:
            previous=conn.execute('SELECT provider,amount_sum,raw_payload FROM payments WHERE idempotency_key=%s',(key,)).fetchone()
        if previous:
            raw=previous['raw_payload'] or {}
            if previous['provider']!='admin' or previous['amount_sum']!=payload.amount_sum or raw.get('reason')!=payload.reason or raw.get('changed_by')!=user['login'] or raw.get('test_credit') is not True:
                raise HTTPException(409, 'Идентификатор уже использован для другой операции')
            return {'ok':True,'already_applied':True,**wash_runtime.snapshot()}
        require_idle(wash_runtime)
        state=wash_runtime.snapshot()['state']
        if state.get('licenseLocked') or state.get('lastIoOk') is not True:
            raise HTTPException(409, 'Проверьте лицензию и связь с оборудованием')
        result=wash_runtime.add_credit(payload.amount_sum,'admin',idempotency_key=key,
            raw_payload={'test_credit':True,'reason':payload.reason,'changed_by':user['login'],'changed_by_user_id':user['id']},bonus_sum=0)
        audit(user,'admin_test_credit',f'Test credit {payload.amount_sum}; operation {payload.operation_id}; {payload.reason}')
        return {'ok':True,'already_applied':False,**result}


@router.get('/service/bill-filter')
def bill_filter_read(user:Admin):
    from .admin_service import io_sync
    with httpx.Client(timeout=4,trust_env=False) as client:
        return io_sync(client,settings.io_helper_url,'/bill/filter')


@router.post('/service/bill-filter')
def bill_filter_save(value:dict,user:Admin):
    from .admin_service import io_sync
    with wash_runtime.lock:
        require_idle(wash_runtime)
        with httpx.Client(timeout=4,trust_env=False) as client:
            result=io_sync(client,settings.io_helper_url,'/bill/filter',value)
    audit(user,'admin_bill_filter_saved','Bill pulse validation settings saved')
    return result


@router.post('/service/bill-filter/reset')
def bill_filter_reset(user:Admin):
    from .admin_service import io_sync
    with wash_runtime.lock:
        require_idle(wash_runtime)
        with httpx.Client(timeout=4,trust_env=False) as client:
            result=io_sync(client,settings.io_helper_url,'/bill/filter/reset',{})
    audit(user,'admin_bill_filter_reset','Bill input fault acknowledged after stable inactive signal')
    return result
