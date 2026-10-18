"""Read-only, signed peer observations. Never grants authority or changes money."""
from datetime import UTC,datetime
from .wallet_domain import WalletConflict
from .wallet_replication import WalletUnavailable

AUTHORITY_FIELDS=('primary_post','standby_post','generation')

def compare(cfg,nodes):
    if cfg.get('single_node'):return 'single-copy'
    if any(not node.get('online') for node in nodes):return 'unavailable'
    if len(nodes)!=2:return 'unavailable'
    proofs=[node['proof'] for node in nodes]
    if any(any(proof.get(key)!=cfg.get(key) for key in AUTHORITY_FIELDS) for proof in proofs):return 'authority-mismatch'
    if any(proof.get('proof_version')!=2 for proof in proofs):return 'protocol-mismatch'
    if any(type(proof.get(key)) is not int or proof[key]<0 for proof in proofs for key in ('pending_count','operation_count')):return 'protocol-mismatch'
    if any(proof.get('pending_count') for proof in proofs):return 'pending'
    if any(proofs[0].get(key)!=proofs[1].get(key) for key in ('journal_digest','state_digest','operation_count')):return 'differs'
    # Missing evidence cannot accidentally compare equal to missing evidence.
    if any(not isinstance(p.get(key),str) or len(p[key])!=64 for p in proofs for key in ('journal_digest','state_digest')):return 'protocol-mismatch'
    return 'in-sync'

def local_proof(cfg,store):
    return {**store.diagnostics(),**{key:cfg[key] for key in AUTHORITY_FIELDS},'local_post':cfg['local_post']}

def observe(cfg,local_snapshot,remote_snapshot):
    checked=datetime.now(UTC).isoformat()
    if not cfg.get('enabled') or not cfg.get('site_id') or not cfg.get('standby_post'):
        return {'ok':True,'checked_at':checked,'state':'not-configured','nodes':[]}
    nodes=[]
    for post in (cfg['primary_post'],cfg['standby_post']):
        try:
            proof=local_snapshot() if post==cfg['local_post'] else remote_snapshot(post)
            if not isinstance(proof,dict) or type(proof.get('local_post')) is not int or proof.get('local_post')!=post:raise WalletConflict('Peer responded with another post number')
            nodes.append({'post':post,'online':True,'proof':proof})
        except (WalletUnavailable,WalletConflict) as exc:
            nodes.append({'post':post,'online':False,'error':str(exc)[:200]})
    return {'ok':True,'checked_at':checked,'state':compare(cfg,nodes),'nodes':nodes,
            'notice':'Read-only observation; it does not authorize failover. Differences may reflect an operation between snapshots.'}
