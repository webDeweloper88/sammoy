"""Shared VIP allowances, isolated from real monetary wallet accounting."""
from copy import deepcopy
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from .wallet_domain import WalletConflict,positive_int


def apply_vip(state,command,*,now,policy):
    next_state=deepcopy(state);action=command['action'];result={'action':action}
    if action in {'configure_vip','remove_vip'}:
        if next_state.assignment or (next_state.vip_visit and next_state.vip_visit.get('assignment')) or next_state.wallet_sum:
            raise WalletConflict('Нельзя менять тип/профиль карты с деньгами или активным допуском')
        if action=='remove_vip':
            next_state.card_type='customer';next_state.vip_profile=None;next_state.vip_visit=None
            next_state.enabled=True;next_state.status='active'
            next_state.service_configuration.pop('vip_import_visits',None)
            next_state.service_configuration.pop('vip_expires_at',None)
        else:
            profile=command.get('profile')
            if not isinstance(profile,dict):raise WalletConflict('VIP profile required')
            grant=profile.get('grant_seconds');maximum=profile.get('max_uses_per_day')
            if type(grant) is not int or not 0 <= grant <= 86400 or (maximum is not None and (type(maximum) is not int or not 1<=maximum<=1000)):
                raise WalletConflict('Invalid VIP grant/limit')
            if type(command.get('enabled',True)) is not bool or command.get('status','active') not in {'active','blocked','lost','expired'}:
                raise WalletConflict('Invalid VIP card status')
            next_state.card_type='vip';next_state.vip_profile=deepcopy(profile)
            next_state.enabled=command.get('enabled',True);next_state.status=command.get('status','active')
            next_state.display_name=str(command.get('display_name') or '')[:120]
            if state.card_type!='vip':next_state.vip_visit=None
            if 'expires_at' in command:
                expiry=command['expires_at']
                if expiry:
                    moment=datetime.fromisoformat(expiry)
                    if moment.tzinfo is None:raise WalletConflict('VIP expiry must include timezone')
                    next_state.service_configuration['vip_expires_at']=expiry
                else:next_state.service_configuration.pop('vip_expires_at',None)
    elif action=='grant_vip':
        profile=command.get('profile_override') or next_state.vip_profile or {}
        if next_state.card_type!='vip' or not next_state.enabled or next_state.status!='active' or not profile.get('enabled',True):
            raise WalletConflict('VIP card is not active')
        expiry=next_state.service_configuration.get('vip_expires_at')
        if expiry and now>=datetime.fromisoformat(expiry):raise WalletConflict('Срок действия VIP-карты истёк')
        visit=next_state.vip_visit
        if visit and visit.get('assignment'):
            raise WalletConflict('VIP-карта уже используется на другом посту')
        assignment_id,visit_id=command.get('assignment_id'),command.get('visit_id')
        if not isinstance(assignment_id,str) or not assignment_id or not isinstance(visit_id,str) or not visit_id:
            raise WalletConflict('VIP visit/assignment identity required')
        post=positive_int(command.get('post_no'),'Post number')
        queue=next_state.service_configuration.get('vip_import_visits',[])
        warm=[v for v in queue if now<datetime.fromisoformat(v['expires_at'])]
        next_state.service_configuration['vip_import_visits']=warm
        warm_existing=visit and visit.get('expires_at') and now<datetime.fromisoformat(visit['expires_at'])
        pauses=[v['pause_millis'] for v in warm]+([visit['pause_millis']] if warm_existing else [])
        inherited_pause=min([policy.free_pause_millis]+pauses)
        if not (warm_existing and visit['remaining_sum']>0):
            candidate=next((v for v in warm if v['remaining_sum']>0),None)
            if candidate:
                warm.remove(candidate);visit=deepcopy(candidate);next_state.vip_visit=visit
                visit['pause_millis']=min(visit['pause_millis'],inherited_pause)
        reusable=visit and visit['remaining_sum']>0 and visit.get('expires_at') and now < datetime.fromisoformat(visit['expires_at'])
        if not reusable:
            day=now.astimezone(ZoneInfo('Asia/Tashkent')).date().isoformat()
            maximum=profile.get('max_uses_per_day');used=next_state.vip_uses.get(day,0)
            if maximum is not None and used>=maximum:raise WalletConflict('VIP daily limit reached')
            if policy.water_amount_sum<=0 or policy.water_duration_seconds<=0:raise WalletConflict('Water reference tariff unavailable')
            value=round(profile['grant_seconds']*policy.water_amount_sum/policy.water_duration_seconds)
            if value<=0:raise WalletConflict('VIP grant is empty')
            next_state.vip_uses[day]=used+1
            result.update(vip_day=day,vip_total_uses=used+1)
            scope=visit if warm_existing else (warm[0] if warm else None)
            visit={'id':scope['id'] if scope else visit_id,'remaining_sum':value,'pause_millis':inherited_pause,
                   'timeout_minutes':scope['timeout_minutes'] if scope else policy.visit_timeout_minutes,'expires_at':None,'profile':deepcopy(profile),
                   'water_reference':{'amount_sum':policy.water_amount_sum,'duration_seconds':policy.water_duration_seconds}}
            next_state.vip_visit=visit
        visit.update(assignment={'id':assignment_id,'post_no':post},expires_at=None)
        result.update(continued=bool(reusable),assignment_id=assignment_id,visit_id=visit['id'],balance_sum=visit['remaining_sum'],
                      pause_millis=visit['pause_millis'],profile=visit['profile'])
    elif action in {'checkpoint_vip','return_vip'}:
        visit=next_state.vip_visit
        a=visit.get('assignment') if visit else None
        if not a or a['id']!=command.get('assignment_id') or a['post_no']!=command.get('post_no'):
            raise WalletConflict('VIP assignment mismatch')
        if action=='checkpoint_vip':
            remaining,pause=command.get('remaining_sum'),command.get('pause_millis')
            if type(remaining) is not int or not 0<=remaining<=visit['remaining_sum'] or type(pause) is not int or not 0<=pause<=visit['pause_millis']:
                raise WalletConflict('VIP allowance cannot be replenished')
            visit.update(remaining_sum=remaining,pause_millis=pause)
        else:
            visit.update(assignment=None,expires_at=(now+timedelta(minutes=visit['timeout_minutes'])).isoformat())
    else:raise WalletConflict('Unknown VIP action')
    next_state.revision+=1;next_state.validate();result['revision']=next_state.revision
    return next_state,result
