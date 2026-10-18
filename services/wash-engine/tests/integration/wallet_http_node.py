"""Isolated HTTP fixture. Never starts WashRuntime or accesses hardware."""
import os
from dataclasses import asdict
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI,Header,HTTPException
from app.config import settings
from app.db import open_pool,db
from app.main import SCHEMA_SQL
from app.wallet_store import WALLET_SCHEMA_SQL,WalletStore
from app.wallet_post import POST_SCHEMA_SQL
from app.wallet_payments import PAYMENT_SCHEMA_SQL
from app.wallet_domain import WalletPolicy
from app.wallet_api import router
from app.auth import current_user

if not settings.postgres_db.startswith('wallet_http_test_'):raise RuntimeError('Refusing non-test DB')
post=int(os.environ['WALLET_TEST_POST'])
open_pool()
with db() as conn:
    conn.execute(SCHEMA_SQL);conn.execute(WALLET_SCHEMA_SQL);conn.execute(POST_SCHEMA_SQL);conn.execute(PAYMENT_SCHEMA_SQL)
    existing=conn.execute("SELECT 1 FROM app_settings WHERE setting_key='shared_wallet'").fetchone()
    if not existing:
        peers={'1':'http://127.0.0.1:18591','7':'http://127.0.0.1:18597','2':'http://127.0.0.1:18592'}
        cfg={'enabled':True,'primary_post':1,'standby_post':7,'generation':1,'single_node':False,'standby_ready':False,'visit_timeout_minutes':30,'peer_urls':peers}
        conn.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('shared_wallet',%s),('license_settings',%s)",
            (Jsonb(cfg),Jsonb({'enabled':False,'site_code':'HTTP_TEST','site_token':'http-test-site-key','post_no':post})))
    conn.commit()
if not existing and post==1:
    with psycopg.connect(settings.database_url,autocommit=True,row_factory=dict_row) as conn:
        store=WalletStore(conn,'HTTP_TEST');store.prepare('opening','7C212602',{'action':'import_opening','amount_sum':35000},WalletPolicy());store.commit_prepared('opening')
app=FastAPI();app.include_router(router)
def owner(authorization:str=Header(default='')):
    if authorization!='Bearer fixture-owner':raise HTTPException(401,'Fixture authentication')
    return {'role':'owner','login':'test-owner','id':1,'must_change_password':False}
app.dependency_overrides[current_user]=owner
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=18591 if post==1 else 18597,access_log=False,log_level='error')
