"""Version 2 wallet: device allowances and restricted bonuses.

No live migration on import. v1 snapshots retain their exact field set; typed
snapshots deliberately contain a field old WalletState cannot deserialize.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
from fractions import Fraction
from .wallet_domain import WalletConflict, WalletState, _apply_command_v1

KINDS=('wash','dry_fog')
DOMAINS=('shared',)+KINDS


def state_dump(state):
    value=asdict(state)
    if value.get('device_wallet') is None:value.pop('device_wallet',None)
    return value


def nonnegative(value):
    return type(value) is int and value>=0


def validate_typed(state):
    m=state.device_wallet
    if not isinstance(m,dict) or m.get('version')!=2:
        raise WalletConflict('Unsupported device wallet version')
    for key,total in [('wallet_bonus',state.wallet_bonus_sum),('assignment_bonus',(state.assignment or {}).get('bonus_sum',0))]:
        groups=m.get(key)
        if not isinstance(groups,dict) or set(groups)!=set(DOMAINS) or any(not nonnegative(v) for v in groups.values()) or sum(groups.values())!=total:
            raise WalletConflict('Device bonus conservation failed')
    for key in ('pause_by_type','vip_pause_by_type'):
        groups=m.get(key)
        if not isinstance(groups,dict) or set(groups)!=set(KINDS) or any(not nonnegative(v) or v>86_400_000 for v in groups.values()):
            raise WalletConflict('Invalid device pause budgets')
    if state.assignment:
        kind=m.get('assignment_type')
        if kind not in KINDS or m['assignment_bonus'][next(k for k in KINDS if k!=kind)]:
            raise WalletConflict('Assignment has incompatible bonus')
        if state.visit['pause_millis']!=m['pause_by_type'][kind]:raise WalletConflict('Device pause alias differs')
    elif m.get('assignment_type') is not None or sum(m['assignment_bonus'].values()):
        raise WalletConflict('Orphan device assignment')
    if state.vip_visit and state.vip_visit.get('assignment'):
        kind=m.get('vip_type')
        if kind not in KINDS or state.vip_visit['pause_millis']!=m['vip_pause_by_type'][kind]:
            raise WalletConflict('VIP device pause alias differs')


def budgets(policy):
    return {'wash':policy.free_pause_millis,'dry_fog':policy.dry_fog_pause_millis}


def migrate(state,policy):
    if state.assignment or (state.vip_visit or {}).get('assignment'):
        raise WalletConflict('Finish the card assignment before device-wallet migration')
    if state.service_configuration.get('vip_import_visits'):
        raise WalletConflict('Resolve legacy imported VIP visits before device-wallet migration')
    state.device_wallet={'version':2,'wallet_bonus':dict.fromkeys(DOMAINS,0),
                         'assignment_bonus':dict.fromkeys(DOMAINS,0),
                         'assignment_type':None,'vip_type':None,
                         'pause_by_type':budgets(policy),'vip_pause_by_type':budgets(policy)}
    m=state.device_wallet;m['wallet_bonus']['shared']=state.wallet_bonus_sum
    if state.visit:m['pause_by_type']['wash']=state.visit['pause_millis']
    if state.vip_visit:m['vip_pause_by_type']['wash']=state.vip_visit['pause_millis']


def spend_groups(groups,amount,kind):
    # Spend the restricted promotional credit first, preserving shared funds.
    for domain in (kind,'shared'):
        used=min(amount,groups[domain]);groups[domain]-=used;amount-=used
    if amount:raise WalletConflict('Bonus spending exceeds eligible domains')


def apply_typed(state,command,*,now,policy):
    if type(command.get('wallet_protocol')) is not int or command['wallet_protocol']!=2:
        raise WalletConflict('This card requires wallet protocol 2 on every post')
    kind=command.get('device_type')
    if kind not in KINDS:raise WalletConflict('Explicit device type required')
    if now.tzinfo is None or now.utcoffset() is None:raise WalletConflict('Authority time must be timezone-aware')
    if state.uid.startswith('@'):raise WalletConflict('Device wallets are for customer cards only')
    state.validate();work=deepcopy(state)
    if work.device_wallet is None:migrate(work,policy)
    meta=work.device_wallet;action=command.get('action')
    if action=='migrate_device_wallet':
        if work.assignment or (work.vip_visit or {}).get('assignment'):raise WalletConflict('Card is assigned')
        work.revision+=1;work.validate()
        return work,{'action':action,'wallet_protocol':2,'revision':work.revision,'wallet_sum':work.wallet_sum}
    if action in {'import_vip','import_local_balance','import_opening','configure_service'}:
        raise WalletConflict('Import/service changes require their explicit migration workflow')
    bound_actions={'accept_load','checkpoint','post_credit','spend','consume_pause','prepare_return','complete_return','register_payment'}
    if action in bound_actions and work.assignment and meta['assignment_type']!=kind:
        raise WalletConflict('Post device type differs from the bound assignment')
    if action in {'checkpoint_vip','return_vip'} and (work.vip_visit or {}).get('assignment') and meta['vip_type']!=kind:
        raise WalletConflict('VIP card is already assigned to another device type')
    domain=command.get('bonus_domain','shared' if policy.bonus_mode=='shared' else kind)
    if domain not in ('shared',kind):raise WalletConflict('Bonus domain is incompatible with the source device')
    funding=[command] if action in {'wallet_credit','open_post'} else command.get('funding',[])
    if not isinstance(funding,list):raise WalletConflict('Invalid funding list')
    for item in funding:
        if not isinstance(item,dict):raise WalletConflict('Invalid funding receipt')
        if item.get('bonus_domain','shared') not in ('shared',kind) or (item.get('bonus_sum',0) and 'bonus_domain' not in item):
            raise WalletConflict('Explicit source bonus domain required')
    # VIP profiles are opt-in by device type. Legacy VIPs remain wash-only.
    command=deepcopy(command)
    if action=='configure_vip':
        p=command.get('profile')
        if not isinstance(p,dict):raise WalletConflict('VIP profile required')
        types=p.get('device_types',['wash'])
        if not isinstance(types,list) or not types or any(not isinstance(k,str) or k not in KINDS for k in types) or len(types)!=len(set(types)):
            raise WalletConflict('Invalid VIP device access')
        p['device_types']=types
    if action=='grant_vip':
        configured=work.vip_profile or {}
        p=command.get('profile_override') or configured
        if kind not in p.get('device_types',['wash']):
            raise WalletConflict('VIP access is not enabled for this device type')
    selected_policy=replace(policy,free_pause_millis=budgets(policy)[kind])
    if kind=='dry_fog':selected_policy=replace(selected_policy,water_amount_sum=policy.dry_fog_amount_sum,water_duration_seconds=policy.dry_fog_duration_seconds)
    old_visit=deepcopy(work.visit);old_vip=deepcopy(work.vip_visit)
    old_bonus=work.wallet_bonus_sum;old_assigned_bonus=(work.assignment or {}).get('bonus_sum',0)
    if action in {'reserve_load','open_post'}:
        if work.visit:work.visit['pause_millis']=meta['pause_by_type'][kind]
    elif work.assignment and action in bound_actions:work.visit['pause_millis']=meta['pause_by_type'][kind]
    if action=='grant_vip' and work.vip_visit:
        visit=work.vip_visit
        visit['pause_millis']=meta['vip_pause_by_type'][kind]
        # Carry the same remaining service time, not a second daily grant.
        ref=visit.get('water_reference',{})
        warm=visit.get('expires_at') and now<datetime.fromisoformat(visit['expires_at'])
        if warm and visit['remaining_sum']>0:
            old_cost,old_secs=ref.get('amount_sum'),ref.get('duration_seconds')
            if not old_cost or not old_secs:raise WalletConflict('VIP conversion reference missing')
            value=int(Fraction(visit['remaining_sum']*old_secs*selected_policy.water_amount_sum,old_cost*selected_policy.water_duration_seconds))
            if value<=0:raise WalletConflict('VIP remainder is too small for this service')
            visit['remaining_sum']=value
            visit['water_reference']={'amount_sum':selected_policy.water_amount_sum,'duration_seconds':selected_policy.water_duration_seconds}
    elif action in {'checkpoint_vip','return_vip'} and work.vip_visit:
        work.vip_visit['pause_millis']=meta['vip_pause_by_type'][kind]
    reserve_amount=reserve_bonus=None
    if action=='reserve_load':
        other=next(k for k in KINDS if k!=kind)
        reserve_amount=work.wallet_sum-meta['wallet_bonus'][other]
        reserve_bonus=meta['wallet_bonus']['shared']+meta['wallet_bonus'][kind]
        if reserve_amount<=0:raise WalletConflict('No balance available for this device type')
    # Legacy arithmetic still enforces money conservation, receipts, revision,
    # assignment ownership, checkpoint monotonicity and return handshake.
    incoming_bonus=dict.fromkeys(DOMAINS,0)
    seen=set(work.funding_receipts)
    if action=='checkpoint':
        for item in funding:
            if not isinstance(item.get('id'),str) or not item['id']:raise WalletConflict('Invalid funding receipt identity')
            if item['id'] not in seen:
                seen.add(item.get('id'));incoming_bonus[item.get('bonus_domain','shared')]+=item.get('bonus_sum',0)
    work.device_wallet=None
    updated,result=_apply_command_v1(work,command,now=now,policy=selected_policy,
                                     reserve_amount=reserve_amount,reserve_bonus=reserve_bonus)
    if action in {'reserve_load','open_post'}:
        fresh=not old_visit or old_visit['id']!=updated.visit['id'] or (old_visit.get('expires_at') and now>=datetime.fromisoformat(old_visit['expires_at']))
        if fresh:meta['pause_by_type']=budgets(policy)
        meta['pause_by_type'][kind]=updated.visit['pause_millis']
        meta['assignment_type']=kind
    elif updated.visit and updated.assignment and action in bound_actions:
        meta['pause_by_type'][kind]=updated.visit['pause_millis']
    if action=='reserve_load':
        for group in (kind,'shared'):
            meta['assignment_bonus'][group]=meta['wallet_bonus'][group];meta['wallet_bonus'][group]=0
    elif action=='open_post':meta['assignment_bonus'][domain]=(updated.assignment or {}).get('bonus_sum',0)
    elif action=='complete_return':
        for group in DOMAINS:
            meta['wallet_bonus'][group]+=meta['assignment_bonus'][group];meta['assignment_bonus'][group]=0
        meta['assignment_type']=None
    elif action=='wallet_credit':meta['wallet_bonus'][domain]+=updated.wallet_bonus_sum-old_bonus
    elif updated.assignment:
        added=updated.bonus_issued_sum-state.bonus_issued_sum
        if action=='checkpoint':
            if sum(incoming_bonus.values())!=added:raise WalletConflict('Funding bonus domains do not reconcile')
            for group in DOMAINS:meta['assignment_bonus'][group]+=incoming_bonus[group]
        else:meta['assignment_bonus'][domain]+=added
        used=old_assigned_bonus+added-updated.assignment.get('bonus_sum',0)
        spend_groups(meta['assignment_bonus'],used,kind)
    if action=='grant_vip':
        fresh=not old_vip or old_vip['id']!=updated.vip_visit['id'] or (old_vip.get('expires_at') and now>=datetime.fromisoformat(old_vip['expires_at']))
        if fresh:meta['vip_pause_by_type']=budgets(policy)
        meta['vip_pause_by_type'][kind]=updated.vip_visit['pause_millis'];meta['vip_type']=kind
    elif action in {'checkpoint_vip','return_vip'}:
        meta['vip_pause_by_type'][kind]=updated.vip_visit['pause_millis']
    elif action=='remove_vip':meta['vip_type']=None;meta['vip_pause_by_type']=budgets(policy)
    updated.device_wallet=meta;updated.validate()
    result.update(wallet_protocol=2,device_type=kind)
    return updated,result


def site_policy(cfg):
    """References belong to device types, independent of the authority's type."""
    from .db import db
    from .wash_logic import normalize_parameters
    from .wallet_domain import WalletPolicy
    with db() as conn:
        rows=conn.execute("SELECT setting_key,setting_value FROM app_settings WHERE setting_key=ANY(%s)",(['wash_parameters','dry_fog_parameters'],)).fetchall()
    values={r['setting_key']:r['setting_value'] for r in rows}
    wash=normalize_parameters(values.get('wash_parameters'),'wash')
    fog=normalize_parameters(values.get('dry_fog_parameters'),'dry_fog')
    water=wash['tariffs']['water'];reference=fog['tariffs']['aroma_1']
    return WalletPolicy(visit_timeout_minutes=cfg['visit_timeout_minutes'],free_pause_millis=int(cfg.get('device_policy',{}).get('wash_pause_seconds',wash['freePauseSeconds'])*1000),
                        water_amount_sum=water['amountSum'],water_duration_seconds=water['durationSeconds'],
                        dry_fog_pause_millis=int(cfg.get('device_policy',{}).get('dry_fog_pause_seconds',fog['freePauseSeconds'])*1000),dry_fog_amount_sum=reference['amountSum'],
                        dry_fog_duration_seconds=reference['durationSeconds'],bonus_mode=cfg.get('bonus_mode','shared'))
