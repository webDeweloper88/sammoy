"""Encrypted report configuration in the replicated site journal."""
import base64
from copy import deepcopy
import hashlib
from urllib.parse import urlsplit
from cryptography.fernet import Fernet,InvalidToken
from .wallet_api import configuration,identity,store_context,coordinator,canonical,control_lock
from .wallet_domain import WalletPolicy
from .wallet_registry import owner_operation

UID='@telegram-state'


def cipher():
    secret=str(identity().get('site_token') or '')
    if not secret:raise ValueError('Site key missing')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('sammoy-report-backup:'+secret).encode()).digest()))


def save_snapshot(snapshot):
    cfg=configuration()
    with control_lock,store_context(cfg) as store:
        existing=store.inspect(UID)
        digest=hashlib.sha256(canonical(snapshot)).hexdigest()
        if existing and existing['state'].get('service_configuration',{}).get('digest')==digest:return
        value={'digest':digest,'ciphertext':cipher().encrypt(canonical(snapshot)).decode()}
        # Retry an uncertain snapshot using its original ciphertext/operation.
        if existing and existing['pending_operation']:
            operation=store.export_operation(existing['pending_operation'])
            coordinator(store,cfg).execute(existing['pending_operation'],UID,operation['command'],WalletPolicy(cfg['visit_timeout_minutes']))
            return
        owner_operation(store,cfg,UID,{'action':'configure_service','value':value,'actor':'telegram-backup'})


def read_snapshot():
    cfg=configuration()
    with control_lock,store_context(cfg) as store:row=store.inspect(UID)
    if not row:return None
    value=row['state'].get('service_configuration',{})
    if not value.get('ciphertext'):return None
    import json
    return json.loads(cipher().decrypt(value['ciphertext'].encode()))


_last_import_digest=None
async def sync():
    global _last_import_digest
    from .main import telegram_setup_request
    cfg=configuration()
    if not cfg['enabled']:return
    primary=cfg['local_post']==cfg['primary_post']
    await telegram_setup_request('leadership','POST',{'active':primary,'primary_post':cfg['primary_post']})
    if cfg['local_post'] not in {cfg['primary_post'],cfg['standby_post']}:return
    if primary:
        snapshot=await telegram_setup_request('backup/export')
        # On promotion, a configured standby already has the bot snapshot. If
        # setup service lost its data, restore the replicated record first.
        prior=read_snapshot()
        if not snapshot.get('env',{}).get('TELEGRAM_BOT_TOKEN') and prior and prior.get('env',{}).get('TELEGRAM_BOT_TOKEN'):
            snapshot=prior
            await telegram_setup_request('backup/import','POST',normalize_posts(snapshot,cfg))
        import asyncio
        await asyncio.to_thread(save_snapshot,snapshot)
    else:
        snapshot=read_snapshot()
        if snapshot:
            snapshot=normalize_posts(snapshot,cfg)
            digest=hashlib.sha256(canonical(snapshot)).hexdigest()
            if digest!=_last_import_digest:
                await telegram_setup_request('backup/import','POST',snapshot)
                _last_import_digest=digest


def normalize_posts(snapshot,cfg):
    result=deepcopy(snapshot)
    for post in result.get('posts',[]):
        try:number=int(str(post['id']).split('-')[-1])
        except (ValueError,KeyError):continue
        if number==cfg['local_post']:post['host']='127.0.0.1'
        elif str(number) in cfg['peer_urls']:post['host']=urlsplit(cfg['peer_urls'][str(number)]).hostname
    return result
