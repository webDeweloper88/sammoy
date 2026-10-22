"""Lightweight signed liveness checks; never synchronize or change authority."""
from datetime import UTC,datetime
from .wallet_replication import WalletUnavailable
from .wallet_domain import WalletConflict


def observe(cfg,remote):
    nodes=[]
    if cfg.get('enabled'):
        for post in dict.fromkeys((cfg['primary_post'],cfg['standby_post'])):
            if post==cfg['local_post']:
                nodes.append({'post':post,'state':'available','reason':None});continue
            try:
                proof=remote(post)
                if not isinstance(proof,dict) or type(proof.get('local_post')) is not int or proof.get('local_post')!=post:
                    raise WalletUnavailable('Unexpected peer identity')
                matches=all(type(proof.get(key)) is int and proof.get(key)==cfg[key] for key in ('primary_post','standby_post','generation'))
                nodes.append({'post':post,'state':'available' if matches else 'mismatch','reason':None if matches else 'authority_mismatch'})
            except (WalletUnavailable,WalletConflict) as error:
                reason='authentication_failed' if any(s in str(error).lower() for s in ('authentication','signature','site key')) else 'connection_failed'
                nodes.append({'post':post,'state':'unavailable','reason':reason})
    return {'ok':True,'checked_at':datetime.now(UTC).isoformat(),'nodes':nodes,
            'generation':cfg.get('generation'),'primary_post':cfg.get('primary_post'),'standby_post':cfg.get('standby_post')}
