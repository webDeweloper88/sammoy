"""Conservative reset guidance from current configuration and durable wallet evidence."""
import hashlib
import json


def classify(local_post, config, history, evidence):
    configured = bool(config.get('enabled') or config.get('standby_post') or config.get('peer_urls') or config.get('management_pending') or config.get('management_last'))
    records = ([config] if configured else []) + list(history)
    participated = bool(evidence or history or config.get('enabled') or config.get('standby_post') or config.get('peer_urls') or config.get('management_pending') or config.get('management_last'))
    role = 'standalone'
    if participated:
        # Previous authority copies also matter after roles or settings change.
        if any(r.get('primary_post', r.get('primary')) == local_post for r in records if r):
            role = 'primary'
        elif any(r.get('standby_post', r.get('standby')) == local_post for r in records if r):
            role = 'standby'
        elif config.get('enabled'):
            role = 'member'
        else:
            role = 'previous_member'
    result = {'role': role, 'local_post': local_post, 'wallet_enabled': bool(config.get('enabled')),
              'has_wallet_history': participated, 'requires_confirmation': participated,
              'requires_peer_isolation': role in ('primary', 'standby', 'previous_member')}
    result['context_id'] = hashlib.sha256(json.dumps([result, {k: config.get(k) for k in ('primary_post','standby_post','generation','peer_urls','management_pending')}], sort_keys=True, default=str).encode()).hexdigest()
    return result


def read_context(conn):
    rows = conn.execute("SELECT setting_key,setting_value FROM app_settings WHERE setting_key IN ('shared_wallet','license_settings','wallet_assignment')").fetchall()
    values = {r['setting_key']: r['setting_value'] for r in rows}
    # Use the same persisted identity as wallet_api.identity().
    from .wallet_api import identity
    local = int(identity().get('post_no') or 1)
    history = [r['context'] for r in conn.execute("SELECT context FROM system_events WHERE source='wallet-owner' AND (context ? 'primary' OR context ? 'standby') ORDER BY id").fetchall()]
    evidence = bool(values.get('wallet_assignment'))
    for table in ('shared_wallet_cards', 'shared_wallet_operations', 'shared_wallet_post_jobs',
                  'shared_wallet_local_imports', 'shared_wallet_vip_imports',
                  'shared_wallet_funding_receipts', 'shared_wallet_vip_uses'):
        # Fixed application table names; no caller-provided SQL identifiers.
        evidence = bool(conn.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone()) or evidence
    return classify(local, values.get('shared_wallet') or {}, history, evidence)
