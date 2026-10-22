#!/usr/bin/env python3
"""Create OS access on a factory clone; never reuses source account passwords."""
import argparse
import base64
import crypt
import json
import os
from pathlib import Path
import secrets
import struct


def public_key(value):
    fields = value.strip().split()
    if len(fields) not in (2, 3) or fields[0] != 'ssh-ed25519':
        raise ValueError('Expected one Ed25519 public key')
    data = base64.b64decode(fields[1], validate=True)
    prefix = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32)
    if len(data) != len(prefix) + 32 or not data.startswith(prefix):
        raise ValueError('Invalid Ed25519 public key')
    return ' '.join(fields) + '\n'


def atomic(path, content, mode=0o600, owner=None):
    path = Path(path)
    if path.is_symlink() or path.with_name(path.name + '.new').exists():
        raise RuntimeError('Unsafe identity destination')
    temp = path.with_name(path.name + '.new')
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w') as out:
        out.write(content)
        out.flush()
        os.fsync(out.fileno())
    if owner is not None:
        os.chown(temp, *owner)
    os.replace(temp, path)


def initialize(root=Path('/')):
    root = Path(root)
    state = root / 'var/lib/sammoy2'
    app = root / 'opt/sammoy/sammoy2'
    if not (state / 'factory-pending').is_file() or not (app / '.factory-identity-ready').is_file():
        raise RuntimeError('Fresh factory identity required')
    if (state / 'os-identity-ready').exists():
        return {'os_identity_ready': True, 'already_initialized': True}
    key = public_key((root / 'etc/sammoy2/installer.pub').read_text())
    users = {}
    for line in (root / 'etc/passwd').read_text().splitlines():
        f = line.split(':')
        if f[0] in ('admin', 'kiosk'):
            users[f[0]] = (int(f[2]), int(f[3]))
            if f[5] != '/home/' + f[0]:
                raise RuntimeError('Unexpected account home')
    if set(users) != {'admin', 'kiosk'}:
        raise RuntimeError('Expected installer and kiosk accounts')
    # Persist before touching shadow so a power-loss retry uses the same password.
    secret_file = state / 'os-first-access.json'
    if not secret_file.exists():
        atomic(secret_file, json.dumps({'admin_password': secrets.token_urlsafe(20),
                                      'kiosk_password': secrets.token_urlsafe(32)}) + '\n')
    values = json.loads(secret_file.read_text())
    replacements = {'root': '!', 'admin': crypt.crypt(values['admin_password'], crypt.mksalt(crypt.METHOD_SHA512)),
                    'kiosk': crypt.crypt(values['kiosk_password'], crypt.mksalt(crypt.METHOD_SHA512))}
    shadow = root / 'etc/shadow'
    rows = []
    seen = set()
    for line in shadow.read_text().splitlines():
        f = line.split(':')
        if f[0] in replacements:
            f[1] = replacements[f[0]]
            seen.add(f[0])
        rows.append(':'.join(f))
    if seen != set(replacements):
        raise RuntimeError('Expected shadow accounts missing')
    st = shadow.stat()
    atomic(shadow, '\n'.join(rows) + '\n', st.st_mode & 0o777, (st.st_uid, st.st_gid))
    home = root / 'home/admin'
    ssh = home / '.ssh'
    if ssh.is_symlink() or home.is_symlink():
        raise RuntimeError('Unexpected installer home symlink')
    ssh.mkdir(mode=0o700, exist_ok=True)
    os.chmod(ssh, 0o700)
    os.chown(ssh, *users['admin'])
    atomic(ssh / 'authorized_keys', key, owner=users['admin'])
    application = json.loads((app / 'factory-access.json').read_text())
    handover = ('LABRIX — first access. Keep this file private.\n'
                'SSH login: admin (installer key required)\n'
                'Linux admin / sudo password: ' + values['admin_password'] + '\n'
                'Owner login: owner\nOwner password: ' + application['owner'] + '\n'
                'Admin login: admin\nAdmin password: ' + application['admin'] + '\n'
                'Change application passwords after installation.\n')
    atomic(home / 'labrix-first-login.txt', handover, owner=users['admin'])
    atomic(state / 'os-identity-ready', '1\n')
    return {'os_identity_ready': True, 'credentials_file': '/home/admin/labrix-first-login.txt'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/')
    print(json.dumps(initialize(Path(parser.parse_args().root))))
