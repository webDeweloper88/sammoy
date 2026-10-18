"""Post-side signed client. Authority discovery does not create new authority."""
from .wallet_domain import WalletConflict
from .wallet_replication import WalletUnavailable


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
            else:status=rpc(cfg,post,'status',{})
            if status.get('local_post')==status.get('primary_post'):
                candidates.append(status)
        except (WalletUnavailable,WalletConflict):pass
    if not candidates:raise WalletUnavailable('Главный пост кошелька недоступен')
    generation=max(c['generation'] for c in candidates)
    newest=[c for c in candidates if c['generation']==generation]
    if len({c['primary_post'] for c in newest})!=1:
        raise WalletUnavailable('Конфликт главных постов: требуется проверка Owner')
    current=newest[0]
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
    if command.get('post_no')!=cfg['local_post']:
        raise WalletConflict('Operation must belong to this post')
    if command.get('bonus_sum',0) or command.get('remaining_bonus_sum',0) or any(r.get('bonus_sum',0) for r in command.get('funding',[])):
        require_bonus_support(cfg)
    return rpc(cfg,cfg['primary_post'],'execute',{'operation_id':operation_id,'uid':uid,'command':command})


def require_bonus_support(cfg):
    from .wallet_api import rpc
    proof=rpc(cfg,cfg['primary_post'],'status',{})
    if proof.get('bonus_protocol')!=1 or proof.get('local_post')!=cfg['primary_post'] or proof.get('generation')!=cfg['generation']:
        raise WalletUnavailable('Обновите главный и резервный посты: нужен учёт бонусного баланса')
