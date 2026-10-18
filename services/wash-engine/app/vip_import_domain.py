"""Import independent local VIP histories once; never create wallet money."""
from copy import deepcopy
from datetime import date,datetime
from hashlib import sha256
import json
from zoneinfo import ZoneInfo
from .wallet_domain import WalletConflict

def receipt(command):
    source=command['snapshot']
    return {'source':'local-vip','post_no':command['post_no'],
            'snapshot_hash':sha256(json.dumps(source,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()}

def apply_import(state,command,*,now,policy):
    s=deepcopy(state);source=command.get('snapshot');post=command.get('post_no')
    if type(post) is not int or not 1<=post<=100 or not isinstance(source,dict) or source.get('uid')!=state.uid:
        raise WalletConflict('Invalid VIP source identity')
    key=f'vip-import:post:{post}:{state.uid}'
    if command.get('receipt_id')!=key:raise WalletConflict('Invalid VIP import receipt')
    value=receipt(command);prior=s.funding_receipts.get(key)
    if prior:
        if prior!=value:raise WalletConflict('Этот источник VIP уже перенесён с другими данными: нужна сверка')
        return s,{'action':'import_vip','already_imported':True}
    if s.wallet_sum or s.assignment or (s.vip_visit or {}).get('assignment'):
        raise WalletConflict('Завершите денежную сессию или активный VIP-допуск карты')
    if s.revision and s.card_type!='vip':raise WalletConflict('UID уже принадлежит денежной карте')
    profile=command.get('profile')
    if not isinstance(profile,dict) or type(profile.get('id')) is not int or type(profile.get('grant_seconds')) is not int or not 0<=profile['grant_seconds']<=86400:
        raise WalletConflict('Invalid common VIP profile')
    if type(source.get('enabled')) is not bool or source.get('status') not in {'active','blocked','lost','expired'} or not isinstance(source.get('display_name'),str) or len(source['display_name'])>120:
        raise WalletConflict('Invalid source VIP status')
    expiry=source.get('expires_at')
    if expiry:
        moment=datetime.fromisoformat(expiry)
        if moment.tzinfo is None:raise WalletConflict('VIP expiry must include timezone')
    if s.revision:
        if (s.vip_profile or {}).get('id')!=profile['id'] or (s.enabled,s.status,s.display_name,s.service_configuration.get('vip_expires_at'))!=(source['enabled'],source['status'],source['display_name'],expiry):
            raise WalletConflict('Профиль или статус VIP расходится: сверите карту на главном посту')
    else:
        s.card_type='vip';s.vip_profile=deepcopy(profile);s.enabled=source['enabled'];s.status=source['status'];s.display_name=source['display_name']
        if expiry:s.service_configuration['vip_expires_at']=expiry
    daily=source.get('daily_uses')
    if not isinstance(daily,dict) or len(daily)>2:raise WalletConflict('Invalid VIP daily history')
    today=now.astimezone(ZoneInfo('Asia/Tashkent')).date()
    totals={}
    for day,used in daily.items():
        if date.fromisoformat(day)>today or type(used) is not int or not 0<=used<=1_000_000:raise WalletConflict('Invalid VIP daily count')
        totals[day]=s.vip_uses.get(day,0)+used;s.vip_uses[day]=totals[day]
    visit=source.get('visit')
    if visit:
        if not isinstance(visit,dict) or type(visit.get('remaining_sum')) is not int or visit['remaining_sum']<0 or type(visit.get('pause_millis')) is not int or not 0<=visit['pause_millis']<=86400000:
            raise WalletConflict('Invalid preserved VIP visit')
        deadline=datetime.fromisoformat(visit['expires_at'])
        if deadline.tzinfo is None:raise WalletConflict('VIP visit must include timezone')
        preserved={**deepcopy(visit),'id':key,'profile':deepcopy(profile),'assignment':None}
        queue=s.service_configuration.setdefault('vip_import_visits',[])
        queue.append(preserved)
    s.funding_receipts[key]=value;s.revision+=1;s.validate()
    return s,{'action':'import_vip','vip_import_uses':totals,'revision':s.revision}
