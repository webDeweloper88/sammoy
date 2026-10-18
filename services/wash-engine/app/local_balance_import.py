"""Durable local card migration. Freeze source before RPC; clear only after ACK."""
from uuid import uuid4
from datetime import UTC,datetime
from psycopg.types.json import Jsonb
from .db import db
from .wallet_api import configuration,authority,rpc
from .wallet_domain import WalletConflict
from .wallet_client import discover_configuration

IMPORT_SCHEMA_SQL='''
CREATE TABLE IF NOT EXISTS shared_wallet_local_imports(
 id UUID PRIMARY KEY,uid TEXT NOT NULL UNIQUE REFERENCES rfid_cards(uid),
 amount_sum BIGINT NOT NULL CHECK(amount_sum>0),source_snapshot JSONB NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','done')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),completed_at TIMESTAMPTZ);
'''


def stage_all(conn,cfg,user):
    """Freeze source balances during an explicitly confirmed mode transition."""
    invalid=conn.execute("SELECT 1 FROM shared_wallet_local_imports j JOIN rfid_cards c ON c.uid=j.uid WHERE c.balance_sum>0 AND (j.status='done' OR j.amount_sum<>c.balance_sum OR j.source_snapshot->>'site_id'<>%s OR (j.source_snapshot->>'post_no')::int<>%s) LIMIT 1",(cfg['site_id'],cfg['local_post'])).fetchone()
    if invalid:raise WalletConflict('Нужна проверка ранее начатого переноса')
    conn.execute("""INSERT INTO shared_wallet_local_imports(id,uid,amount_sum,source_snapshot,status)
      SELECT gen_random_uuid(),uid,balance_sum,jsonb_build_object('uid',uid,'enabled',enabled,
          'status',CASE WHEN expires_at<=now() THEN 'expired' ELSE status END,'display_name',display_name,
          'balance_sum',balance_sum,'bonus_sum',bonus_sum,'actor',%s::text,'post_no',%s::int,'site_id',%s::text),'pending'
      FROM rfid_cards WHERE card_type='customer' AND balance_sum>0 ON CONFLICT(uid) DO NOTHING""",
      (user['login'],cfg['local_post'],cfg['site_id']))
    conn.execute("UPDATE rfid_cards SET enabled=false,updated_at=now() WHERE uid IN (SELECT uid FROM shared_wallet_local_imports WHERE status='pending')")


def preview(after='',limit=30):
    cfg=configuration()
    with db() as conn:
        rows=conn.execute("SELECT c.uid,c.balance_sum,c.status,c.enabled,c.display_name,j.id AS import_id,j.status AS import_status,j.amount_sum AS import_sum FROM rfid_cards c LEFT JOIN shared_wallet_local_imports j ON j.uid=c.uid WHERE c.card_type='customer' AND (c.balance_sum>0 OR j.status='pending') AND c.uid>%s ORDER BY c.uid LIMIT %s",(after,limit+1)).fetchall()
    return {'ok':True,'post_no':cfg['local_post'],'enabled':cfg['enabled'],'truncated':False,'next_after':rows[limit-1]['uid'] if len(rows)>limit else None,'cards':[{**row,'import_id':str(row['import_id']) if row['import_id'] else None} for row in rows[:limit]]}


def transfer(uid,expected_amount,confirmation,user,*,prepare_only=False):
    cfg=configuration();authority(cfg)
    if confirmation!=f'IMPORT {uid} {expected_amount}':raise WalletConflict('Подтвердите UID и сумму переноса')
    with db() as conn:
        card=conn.execute('SELECT * FROM rfid_cards WHERE uid=%s FOR UPDATE',(uid,)).fetchone()
        if not card or card['card_type']!='customer':raise WalletConflict('Локальная денежная карта не найдена')
        job=conn.execute('SELECT * FROM shared_wallet_local_imports WHERE uid=%s',(uid,)).fetchone()
        if job and job['status']=='done':return {'ok':True,'already_imported':True}
        amount=int(job['amount_sum'] if job else card['balance_sum'])
        if amount!=expected_amount or amount<=0:raise WalletConflict('Локальный остаток изменился: обновите список')
        if not job:
            snapshot={key:card[key] for key in ('uid','enabled','status','display_name','balance_sum','bonus_sum')}
            if card.get('expires_at') and card['expires_at']<=datetime.now(UTC):snapshot['status']='expired'
            snapshot.update(actor=user['login'],transfer_actor=user['login'],post_no=cfg['local_post'],site_id=cfg['site_id'])
            ident=uuid4()
            conn.execute("INSERT INTO shared_wallet_local_imports VALUES(%s,%s,%s,%s,'pending',now(),NULL)",(ident,uid,amount,Jsonb(snapshot)))
            conn.execute('UPDATE rfid_cards SET enabled=false,updated_at=now() WHERE uid=%s',(uid,))
            job={'id':ident,'amount_sum':amount,'source_snapshot':snapshot}
        if 'transfer_actor' not in job['source_snapshot']:
            source={**job['source_snapshot'],'transfer_actor':user['login']}
            conn.execute('UPDATE shared_wallet_local_imports SET source_snapshot=%s WHERE uid=%s',(Jsonb(source),uid))
            job['source_snapshot']=source
        conn.commit()
    if prepare_only:return {'ok':True,'prepared':True}
    cfg=discover_configuration()
    source=job['source_snapshot']
    if source['post_no']!=cfg['local_post'] or source['site_id']!=cfg['site_id']:raise WalletConflict('Исходный номер поста изменился')
    command={'action':'import_local_balance','post_no':cfg['local_post'],'amount_sum':amount,
             'bonus_sum':int(source.get('bonus_sum') or 0),'receipt_id':'local-import:'+str(job['id']),'enabled':source['enabled'],'status':source['status'],
             'display_name':source['display_name'],'actor':source.get('transfer_actor',source['actor'])}
    if command.get('bonus_sum'):
        from .wallet_client import require_bonus_support
        require_bonus_support(cfg)
    rpc(cfg,cfg['primary_post'],'import-local',{'uid':uid,'operation_id':command['receipt_id'],'command':command})
    with db() as conn:
        card=conn.execute('SELECT balance_sum FROM rfid_cards WHERE uid=%s FOR UPDATE',(uid,)).fetchone()
        current=conn.execute('SELECT status FROM shared_wallet_local_imports WHERE uid=%s FOR UPDATE',(uid,)).fetchone()
        if current['status']=='done':return {'ok':True,'already_imported':True}
        if int(card['balance_sum'])!=amount:raise WalletConflict('Исходный баланс изменён после подтверждения: требуется проверка Owner')
        conn.execute('UPDATE rfid_cards SET balance_sum=0,bonus_sum=0,enabled=false,updated_at=now() WHERE uid=%s',(uid,))
        conn.execute("INSERT INTO rfid_card_ledger(card_uid,direction,reason,amount_sum,balance_after_sum,raw_payload) VALUES(%s,'debit','admin_adjustment',%s,0,%s)",(uid,amount,Jsonb({'migration_operation':command['receipt_id'],'actor':user['login']})))
        conn.execute("UPDATE shared_wallet_local_imports SET status='done',completed_at=now() WHERE uid=%s",(uid,));conn.commit()
    return {'ok':True,'amount_sum':amount}
