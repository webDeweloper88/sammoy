"""Owner customer registry; metadata edits never alter money or pause budget."""
from pydantic import BaseModel,ConfigDict,Field
from .wallet_api import configuration,authority,store_context,control_lock,rpc
from .wallet_domain import WalletConflict
from .wallet_registry import owner_operation

from .schema import CustomerRequest


def page(store,after='',limit=30):
    rows=store.conn.execute("SELECT uid,state,pending_operation FROM shared_wallet_cards WHERE site_id=%s AND state->>'card_type'='customer' AND uid NOT LIKE '@%%' AND uid>%s ORDER BY uid LIMIT %s",(store.site_id,after,limit+1)).fetchall()
    return {'ok':True,'cards':[{'uid':row['uid'],'display_name':row['state'].get('display_name',''),
        'status':row['state']['status'],'enabled':row['state']['enabled'],'balance_sum':row['state']['wallet_sum'],
        'bonus_sum':row['state'].get('wallet_bonus_sum',0),
        'assigned_sum':(row['state'].get('assignment') or {}).get('balance_sum',0),
        'assigned_post':(row['state'].get('assignment') or {}).get('post_no'),
        'revision':row['state']['revision'],'pending':bool(row['pending_operation'])} for row in rows[:limit]],
        'next_after':rows[limit-1]['uid'] if len(rows)>limit else None}


def read(after='',limit=30):
    cfg=configuration();authority(cfg)
    if cfg['local_post']!=cfg['primary_post']:
        from .wallet_client import discover_configuration
        cfg=discover_configuration()
        return {**rpc(cfg,cfg['primary_post'],'customer-registry',{'after':after,'limit':limit}),'can_edit':False}
    with control_lock,store_context(cfg) as store:return {**page(store,after,limit),'can_edit':True}


def save(payload,user):
    cfg=configuration();authority(cfg).require_primary();uid=payload.uid.upper()
    with control_lock,store_context(cfg) as store:
        current=store.inspect(uid)
        revision=current['state']['revision'] if current else 0
        if revision!=payload.expected_revision:raise WalletConflict('Карта изменилась: обновите список и повторите')
        owner_operation(store,cfg,uid,{'action':'configure_customer','display_name':payload.display_name.strip(),
                                     'status':payload.status,'enabled':payload.enabled,'actor':user['login']})
    return {'ok':True}
