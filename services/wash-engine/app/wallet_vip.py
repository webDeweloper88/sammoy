"""Post-side VIP grant continuation, without creating monetary wallet funds."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from .db import db
from .wallet_domain import WalletConflict
from .wallet_post import pending_job,assignment,freeze,set_job,apply_load,apply_return,pause_millis,protocol_fields
from . import wallet_client
from .wallet_operation import card_operation


@card_operation()
def handle_card(runtime,uid,event):
    runtime.state['walletTransferVip']=True
    job=pending_job();ctx=assignment()
    if job and (job['uid']!=uid or not job['payload'].get('is_vip')):
        raise WalletConflict('На посту завершается операция другой карты')
    if not job:
        cfg=wallet_client.discover_configuration()
        if ctx and (ctx['uid']!=uid or not ctx.get('is_vip')):
            raise WalletConflict('Завершите текущую клиентскую сессию')
        if int(runtime.state.get('creditSum') or 0)>0 and runtime.active_session_source!='vip':
            raise WalletConflict('Денежный баланс нельзя смешивать с VIP-допуском')
        freeze(runtime)
        if ctx:
            p={'stage':'checkpoint','is_vip':True,'post_no':cfg['local_post'],'assignment_id':ctx['assignment_id'],
               'visit_id':ctx['visit_id'],'session_id':ctx['session_id'],'amount_sum':int(runtime.state.get('creditSum') or 0),
               'pause_millis':pause_millis(runtime) if runtime.state.get('creditSum') else 0,'payment_cursor':ctx['payment_cursor'],'cash_cursor':0}
            kind='return'
        else:
            p={'stage':'grant','is_vip':True,'post_no':cfg['local_post'],'assignment_id':uuid4().hex,'visit_id':uuid4().hex}
            kind='load'
        p.update(protocol_fields(runtime,cfg,wallet_client.inspect(uid),ctx))
        job_id=uuid4().hex
        with db() as conn:
            conn.execute('INSERT INTO shared_wallet_post_jobs(id,uid,kind,payload) VALUES(%s,%s,%s,%s)',(job_id,uid,kind,Jsonb(p)));conn.commit()
        job={'id':job_id,'uid':uid,'kind':kind,'payload':p}
    freeze(runtime);p=job['payload'];base={'post_no':p['post_no'],'assignment_id':p['assignment_id']}
    if p.get('wallet_protocol')==2:base.update({k:p[k] for k in ('wallet_protocol','device_type','bonus_domain')})
    def remote(step,command):return wallet_client.execute(job['id']+':'+step,uid,{**base,**command})['result']
    if job['kind']=='load':
        if p['stage']=='grant':
            r=remote('grant',{'action':'grant_vip','visit_id':p['visit_id']})
            p.update(stage='apply',amount_sum=r['balance_sum'],visit_id=r['visit_id'],pause_millis=r['pause_millis'],profile=r['profile'],continued=r['continued'])
            set_job(job,p)
        apply_load(runtime,job)
        runtime.state['lastRfidStatus']='vip_granted'
    else:
        if p['stage']=='checkpoint':
            remote('checkpoint',{'action':'checkpoint_vip','remaining_sum':p['amount_sum'],'pause_millis':p['pause_millis']})
            p['stage']='complete';set_job(job,p)
        remote('complete',{'action':'return_vip'})
        apply_return(runtime,job)
        runtime.state['lastRfidStatus']='vip_session_closed'
