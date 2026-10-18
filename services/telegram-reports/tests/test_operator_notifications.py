import asyncio
from uuid import uuid4
from unittest.mock import patch
import httpx
from fastapi import FastAPI,HTTPException
import pytest
from app.operator_notifications import register,CallRequest
@pytest.fixture
def queue(tmp_path):
 env={'SITE_ID':'SITE','TELEGRAM_BOT_TOKEN':'fake-test-token','TELEGRAM_ENABLED':'true','TELEGRAM_LEADER':'true'}
 class Pairing:
  def __init__(self,path):pass
  def owner(self):return {'telegram_user_id':123}
 return (*register(FastAPI(),lambda:env,tmp_path/'hub.sqlite3',Pairing),env,tmp_path)
def request(post=1):return CallRequest(request_id=uuid4(),site_id='SITE',post_no=post)
def test_idempotence_cooldown_and_post_separation(queue):
 enqueue,status,_,_,_=queue;r=request();one=enqueue(r);assert one==enqueue(r)
 assert enqueue(request())['request_id']==one['request_id']
 assert enqueue(request(2))['request_id']!=one['request_id']
 assert status(r.request_id)['status']=='queued'
def test_unconfigured_does_not_enqueue(queue):
 enqueue,_,_,env,_=queue;env['TELEGRAM_BOT_TOKEN']=''
 with pytest.raises(HTTPException):enqueue(request())
def test_success_requires_telegram_confirmation_and_no_repeat(queue):
 enqueue,status,deliver,env,path=queue;r=request();enqueue(r);seen=[]
 def handler(req):
  seen.append(req);return httpx.Response(200,json={'ok':True,'result':{'message_id':7}})
 original=httpx.AsyncClient
 with patch('app.operator_notifications.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
  asyncio.run(deliver());asyncio.run(deliver())
 assert len(seen)==1;assert status(r.request_id)['status']=='sent'
 assert b'CARD' not in seen[0].content
 # A new process/store instance reads the same durable result.
 _,again,_=register(FastAPI(),lambda:env,path/'hub.sqlite3',lambda p:None)
 assert again(r.request_id)['status']=='sent'
def test_timeout_is_unknown_and_not_retried(queue):
 enqueue,status,deliver,_,_=queue;r=request();enqueue(r);seen=[]
 def handler(req):seen.append(req);raise httpx.ReadTimeout('lost reply')
 original=httpx.AsyncClient
 with patch('app.operator_notifications.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
  asyncio.run(deliver());asyncio.run(deliver())
 assert status(r.request_id)['status']=='unknown';assert len(seen)==1
def test_expiry_and_standby_do_not_send(queue):
 import sqlite3,time
 enqueue,status,deliver,env,path=queue;r=request();enqueue(r)
 with sqlite3.connect(path/'operator-calls.sqlite3') as c:c.execute('UPDATE calls SET created=?',(time.time()-301,))
 with patch('app.operator_notifications.httpx.AsyncClient') as client:
  asyncio.run(deliver());client.assert_not_called()
 assert status(r.request_id)['status']=='expired'
 env['TELEGRAM_LEADER']='false'
 with pytest.raises(HTTPException):enqueue(request(2))

def test_explicit_rate_limit_is_queued_with_backoff(queue):
 enqueue,status,deliver,_,_=queue;r=request();enqueue(r);seen=[]
 def handler(req):seen.append(req);return httpx.Response(429,json={'ok':False,'parameters':{'retry_after':60}})
 original=httpx.AsyncClient
 with patch('app.operator_notifications.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
  asyncio.run(deliver());asyncio.run(deliver())
 assert status(r.request_id)['status']=='queued';assert len(seen)==1
