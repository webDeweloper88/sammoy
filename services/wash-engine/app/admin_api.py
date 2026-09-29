from datetime import datetime, UTC
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
async def network_action(action:Literal['apply','confirm','rollback'],payload:dict,user:Admin):
    if action=='apply':require_idle(wash_runtime)
    result=await network_request('/'+action,'POST',payload)
    audit(user,'admin_network_'+action,'Network '+action+' requested')
    return result
