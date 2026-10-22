#!/usr/bin/env python3
"""Initialize application secrets on a NEW golden-image clone only."""
import argparse
import json
import os
from pathlib import Path
import secrets

# Installer-facing application defaults. Infrastructure and Linux credentials
# remain unique to each clone. The backend requires a new password on first login.
DEFAULT_OWNER_PASSWORD = 'labrix'
DEFAULT_ADMIN_PASSWORD = 'labrix'


def initialize(root):
    root = Path(root)
    if not (root / 'GOLDEN_TEMPLATE.json').is_file():
        raise RuntimeError('Not an exported golden template')
    env = root / '.env'
    if env.exists():
        raise RuntimeError('Identity already exists; refusing to rotate secrets')
    data = root / 'data'
    if data.exists() and any(data.iterdir()):
        raise RuntimeError('Data already exists; refusing initialization')
    values = {
        'COMPOSE_PROJECT_NAME': 'sammoy2',
        'POSTGRES_DB': 'sammoy2', 'POSTGRES_USER': 'sammoy2',
        'POSTGRES_PASSWORD': secrets.token_hex(32),
        'WASH_ENGINE_JWT_SECRET': secrets.token_hex(48),
        'WASH_ENGINE_DEFAULT_OWNER_PASSWORD': DEFAULT_OWNER_PASSWORD,
        'WASH_ENGINE_DEFAULT_ADMIN_PASSWORD': DEFAULT_ADMIN_PASSWORD,
        'TELEGRAM_SETUP_KEY': secrets.token_hex(32),
        'REPORT_API_KEY': secrets.token_hex(32),
    }
    values['REPORT_POSTGRES_DSN'] = 'postgresql://sammoy2:'+values['POSTGRES_PASSWORD']+'@postgres:5432/sammoy2'
    # Exclusive create is also the retry guard. Never replace an active .env.
    fd = os.open(str(env), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(''.join(key+'='+value+'\n' for key,value in values.items()))
        stream.flush(); os.fsync(stream.fileno())
    handover = root / 'factory-access.json'
    fd = os.open(str(handover), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'owner': values['WASH_ENGINE_DEFAULT_OWNER_PASSWORD'], 'admin': values['WASH_ENGINE_DEFAULT_ADMIN_PASSWORD'], 'must_change_password': True}, stream)
    data.mkdir(exist_ok=True)
    for name in ('postgres', 'io-helper', 'kiosk-assets'):
        (data / name).mkdir(mode=0o700, exist_ok=True)
    ready = root / '.factory-identity-ready'
    ready.write_text('1\n')
    os.chmod(ready, 0o600)
    return {'initialized': True, 'credentials_file': str(handover)}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    print(json.dumps(initialize(parser.parse_args().root)))
