"""Post-side signed client. Authority discovery does not create new authority."""
from .wallet_domain import WalletConflict
from .wallet_replication import WalletUnavailable
from .wallet_operation import status_proof


def enabled():
    from .wallet_api import configuration
    return configuration()['enabled']


def discover_configuration():
    from .wallet_api import configuration,rpc,persist_configuration,control_lock
    cfg=configuration()
    if not cfg['enabled']:raise WalletUnavailable('Shared wallet disabled')
    candidates=[]
    for post in set((cfg['primary_post'],cfg['standby_post'])):
        if not post:continue
        try:
            own_url=cfg['peer_urls'].get(str(cfg['local_post']))
            if not own_url:raise WalletUnavailable('Адрес этого поста не задан')
            # The primary authenticates and enrolls the post before status/read.
            if cfg['local_post'] not in {cfg['primary_post'],cfg['standby_post']}:
                from .vip_migration import source_status
                local=source_status()
                status=rpc(cfg,post,'enroll',{'url':own_url,'vip_migration_pending':bool(local['pending'] or local['legacy'])})
            else:status=status_proof(cfg,post)
            if status.get('local_post')==status.get('primary_post'):
                candidates.append(status)
        except (WalletUnavailable,WalletConflict):pass
    if not candidates:raise WalletUnavailable('Главный пост кошелька недоступен')
    generation=max(c['generation'] for c in candidates)
    newest=[c for c in candidates if c['generation']==generation]
    if len({c['primary_post'] for c in newest})!=1:
        raise WalletUnavailable('Конфликт главных постов: требуется проверка Owner')
    current=newest[0]
    cfg.update(bonus_mode=current.get('bonus_mode','shared'),device_wallet_enabled=current.get('device_wallet_enabled',False),device_policy=current.get('device_policy'),device_types=current.get('device_types',{}))
    if generation < cfg['generation']:raise WalletUnavailable('Найден только устаревший главный пост')
    if generation > cfg['generation']:
        # Ordinary posts learn an already authorized role change. Configured
        # standby nodes must use explicit rejoin/synchronization instead.
        if cfg['local_post'] in {cfg['primary_post'],cfg['standby_post']}:
            raise WalletUnavailable('Узел кошелька требует синхронизации после смены главного')
        with control_lock:
            cfg.update(primary_post=current['primary_post'],standby_post=current['standby_post'],
                       generation=generation,single_node=current['single_node'])
            persist_configuration(cfg,{'login':'wallet-discovery'},'wallet_authority_discovered')
    return cfg


def inspect(uid):
    from .wallet_api import rpc
    cfg=discover_configuration()
    return rpc(cfg,cfg['primary_post'],'inspect',{'uid':uid}).get('card')


def execute(operation_id,uid,command):
    from .wallet_api import rpc
    cfg=discover_configuration()
    if command.get('wallet_protocol')==2:require_device_wallet_support(cfg)
    if command.get('post_no')!=cfg['local_post']:
        raise WalletConflict('Operation must belong to this post')
    if command.get('bonus_sum',0) or command.get('remaining_bonus_sum',0) or any(r.get('bonus_sum',0) for r in command.get('funding',[])):
        require_bonus_support(cfg)
    return rpc(cfg,cfg['primary_post'],'execute',{'operation_id':operation_id,'uid':uid,'command':command,'expected_authority':{k:cfg[k] for k in ('primary_post','generation')}})


def require_bonus_support(cfg):
    from .wallet_api import rpc
    proof=status_proof(cfg,cfg['primary_post'])
    if proof.get('bonus_protocol')!=1 or proof.get('local_post')!=cfg['primary_post'] or proof.get('generation')!=cfg['generation']:
        raise WalletUnavailable('Обновите главный и резервный посты: нужен учёт бонусного баланса')


def require_device_wallet_support(cfg, *, local_capability=False):
    """Refuse migration/typed operations before preparing a financial journal entry."""
    from .wallet_api import rpc
    nodes={cfg['primary_post']}
    if not cfg.get('single_node'):nodes.add(cfg['standby_post'])
    for post in nodes:
        if local_capability and post==cfg.get('local_post'):continue
        proof=status_proof(cfg,post)
        if proof.get('device_wallet_protocol')!=2 or proof.get('local_post')!=post or proof.get('generation')!=cfg['generation'] or proof.get('primary_post')!=cfg['primary_post']:
            raise WalletUnavailable('Обновите главный и резервный посты: нужен протокол кошелька 2')
