"""Owner-managed common VIP registry using the same replicated journal."""
import hashlib
from .wallet_domain import WalletPolicy,WalletConflict
from .wallet_api import configuration,authority,store_context,coordinator,canonical,rpc,control_lock

PROFILES_UID='@vip-profiles'


def profile_value(store):
    row=store.inspect(PROFILES_UID)
    return row['state'].get('service_configuration',{}).get('profiles',[]) if row else []


def read_registry():
    from .wallet_client import discover_configuration
    cfg=discover_configuration()
    return rpc(cfg,cfg['primary_post'],'registry-read',{})


def owner_operation(store,cfg,uid,command):
    current=store.inspect(uid)
    revision=current['state']['revision'] if current else 0
    op='owner:'+hashlib.sha256(canonical({'uid':uid,'revision':revision,'command':command})).hexdigest()
    return coordinator(store,cfg).execute(op,uid,command,WalletPolicy(cfg['visit_timeout_minutes']))


def save_profiles(payload,user):
    cfg=configuration();authority(cfg).require_primary()
    with control_lock,store_context(cfg) as store:
        current=profile_value(store);ids={p['code']:p['id'] for p in current};next_id=max([p['id'] for p in current]+[0])+1
        values=[];codes=set();profile_ids=set()
        for item in payload.profiles:
            p=item.model_dump();p['code']=p['code'].strip().upper();p['name']=p['name'].strip()
            if not p['code'] or not p['name'] or p['code'] in codes:raise WalletConflict('Проверьте названия и уникальные коды VIP-профилей')
            if p.get('id') is None:
                p['id']=ids.get(p['code'],next_id)
                if p['id']==next_id:next_id+=1
            if p['id'] in profile_ids:raise WalletConflict('Duplicate VIP profile ID')
            codes.add(p['code']);profile_ids.add(p['id']);values.append(p)
        merged={p['id']:p for p in current}
        for p in values:merged[p['id']]=p
        values=sorted(merged.values(),key=lambda p:p['id'])
        if len({p['code'] for p in values})!=len(values):raise WalletConflict('Код VIP-профиля уже используется')
        owner_operation(store,cfg,PROFILES_UID,{'action':'configure_service','value':{'profiles':values},'actor':user['login']})
    return {'ok':True,'profiles':values,'updated_by':user['login']}


def save_card(payload,user):
    cfg=configuration();authority(cfg).require_primary();uid=payload.uid.strip().upper()
    with control_lock,store_context(cfg) as store:
        profiles=profile_value(store);profile=next((p for p in profiles if p['id']==payload.vip_profile_id),None)
        if not profile:raise WalletConflict('VIP profile not found')
        owner_operation(store,cfg,uid,{'action':'configure_vip','profile':profile,'enabled':payload.enabled,'status':payload.status,
                                     'display_name':payload.display_name.strip(),'actor':user['login'],**({'expires_at':payload.expires_at} if 'expires_at' in payload.model_fields_set else {})})
        card=serialize_card(store.inspect(uid)['state'],profiles)
    return {'ok':True,'card':card,'updated_by':user['login']}


def remove_card(uid,user):
    cfg=configuration();authority(cfg).require_primary()
    with control_lock,store_context(cfg) as store:
        current=store.inspect(uid.upper())
        if not current or current['state'].get('card_type')!='vip':raise WalletConflict('VIP card not found')
        owner_operation(store,cfg,uid.upper(),{'action':'remove_vip','actor':user['login']})
    return {'ok':True}


def serialize_card(state,profiles):
    profile=state.get('vip_profile') or {};actual=next((p for p in profiles if p['id']==profile.get('id')),profile)
    return {'uid':state['uid'],'card_type':state['card_type'],'status':state['status'],'enabled':state['enabled'],
            'display_name':state.get('display_name',''),'balance_sum':state['wallet_sum'],'vip_profile_id':profile.get('id'),
            'vip_profile_code':actual.get('code'),'vip_profile_name':actual.get('name'),
            'created_at':None,'updated_at':None,'last_seen_at':None,'expires_at':state.get('service_configuration',{}).get('vip_expires_at')}


def registry_payload(store):
    day=store.conn.execute("SELECT (clock_timestamp() AT TIME ZONE 'Asia/Tashkent')::date AS usage_day").fetchone()['usage_day'].isoformat()
    uses={r['uid']:r['used'] for r in store.conn.execute('SELECT uid,used FROM shared_wallet_vip_uses WHERE site_id=%s AND day=%s',(store.site_id,day)).fetchall()}
    profiles=profile_value(store)
    return {'ok':True,'profiles':profiles,'cards':[{**serialize_card(r['state'],profiles),'uses_today':uses.get(r['state']['uid'],0),'usage_day':day,'active_post':((r['state'].get('vip_visit') or {}).get('assignment') or {}).get('post_no')} for r in store.vip_cards()]}
