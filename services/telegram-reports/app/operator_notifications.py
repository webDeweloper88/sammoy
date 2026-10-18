"""Durable, bounded operator notifications; never retry an ambiguous delivery."""
import asyncio
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID
import httpx
from fastapi import HTTPException
from pydantic import BaseModel,Field

class CallRequest(BaseModel):
    request_id:UUID
    site_id:str=Field(min_length=1,max_length=80)
    post_no:int=Field(ge=1,le=100)
    destination:str=Field(default='',pattern=r'^-?[0-9]{1,20}$|^$',max_length=21)

def register(app,read_env,data_path,pairing_store):
    path=data_path.parent/'operator-calls.sqlite3'
    def connect():
        path.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(path,timeout=10);c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,site TEXT NOT NULL,post INTEGER NOT NULL,destination TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,next_attempt REAL NOT NULL,message_id TEXT)')
        return c
    def view(row):return {'ok':True,'request_id':row['id'],'status':row['status'],'retry_after':max(0,int(row['created']+120-time.time()))}
    @app.post('/operator/call')
    def enqueue(payload:CallRequest):
        env=read_env()
        if env.get('SITE_ID')!=payload.site_id or env.get('TELEGRAM_LEADER','true')!='true':raise HTTPException(503,'Operator service is not primary')
        owner=pairing_store(data_path).owner()
        destination=payload.destination or (str(owner['telegram_user_id']) if owner else '')
        if not env.get('TELEGRAM_BOT_TOKEN') or env.get('TELEGRAM_ENABLED')!='true' or not destination:raise HTTPException(409,'Configure Telegram and operator recipient first')
        now=time.time()
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM calls WHERE id=?',(str(payload.request_id),)).fetchone()
            if old:
                if (old['site'],old['post'])!=(payload.site_id,payload.post_no):raise HTTPException(409,'Request identity conflict')
                return view(old)
            old=c.execute('SELECT * FROM calls WHERE site=? AND post=? AND created>? ORDER BY created DESC LIMIT 1',(payload.site_id,payload.post_no,now-120)).fetchone()
            if old:return view(old)
            c.execute('DELETE FROM calls WHERE created<?',(now-31*86400,))
            c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)',(str(payload.request_id),payload.site_id,payload.post_no,destination,'queued',now,now,None))
            return view(c.execute('SELECT * FROM calls WHERE id=?',(str(payload.request_id),)).fetchone())
    @app.get('/operator/call/{request_id}')
    def status(request_id:UUID):
        with connect() as c:row=c.execute('SELECT * FROM calls WHERE id=?',(str(request_id),)).fetchone()
        if not row:raise HTTPException(404,'Call not found')
        return view(row)
    async def deliver_once():
        env=read_env()
        if env.get('TELEGRAM_LEADER','true')!='true' or env.get('TELEGRAM_ENABLED')!='true' or not env.get('TELEGRAM_BOT_TOKEN'):return
        now=time.time()
        with connect() as c:
            if not c.execute("SELECT 1 FROM calls WHERE status='sending' OR (status='queued' AND (next_attempt<=? OR created<?)) LIMIT 1",(now,now-300)).fetchone():return
            # Sending at process death is ambiguous: do not send it again.
            c.execute("UPDATE calls SET status='unknown' WHERE status='sending'")
            c.execute("UPDATE calls SET status='expired' WHERE status='queued' AND created<?",(now-300,))
            row=c.execute("SELECT * FROM calls WHERE status='queued' AND next_attempt<=? AND site=? ORDER BY created LIMIT 1",(now,env.get('SITE_ID',''))).fetchone()
            if not row:return
            token=env.get('TELEGRAM_BOT_TOKEN')
            if not token or env.get('TELEGRAM_ENABLED')!='true':return
            c.execute("UPDATE calls SET status='sending' WHERE id=?",(row['id'],))
        stamp=datetime.fromtimestamp(row['created'],ZoneInfo('Asia/Tashkent')).strftime('%d.%m.%Y %H:%M:%S')
        text=f"Вызов оператора\nМойка: {row['site']}\nПост: {row['post']:02d}\nКлиент просит помощь.\nВремя: {stamp}"
        result='unknown';message_id=None;next_attempt=now+30
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response=await client.post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':row['destination'],'text':text})
            data=response.json()
            if response.status_code==200 and data.get('ok'):
                result='sent';message_id=str(data['result']['message_id'])
            elif response.status_code==429:
                result='queued';next_attempt=now+max(30,min(300,int(data.get('parameters',{}).get('retry_after',30))))
            elif response.status_code>=500:result='unknown'
            else:result='failed'
        except (httpx.ConnectError,httpx.ConnectTimeout):result='queued'
        except (httpx.HTTPError,ValueError,KeyError):pass
        with connect() as c:c.execute('UPDATE calls SET status=?,message_id=?,next_attempt=? WHERE id=?',(result,message_id,next_attempt,row['id']))
    task=None
    async def worker():
        while True:
            try:await deliver_once()
            except Exception:pass
            await asyncio.sleep(2)
    @app.on_event('startup')
    async def start():
        nonlocal task
        task=asyncio.create_task(worker())
    @app.on_event('shutdown')
    async def stop():
        if task:
            task.cancel()
            from contextlib import suppress
            with suppress(asyncio.CancelledError):await task
    return enqueue,status,deliver_once
