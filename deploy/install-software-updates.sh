#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo'; exit 1; }
cd /opt/sammoy/sammoy2
[ "$#" = 1 ] && [ -f "$1" ] || { echo 'Usage: sudo deploy/install-software-updates.sh trusted-public-key.pem'; exit 1; }
board=$(/usr/bin/python3 - <<'PYBOARD'
import json,os,pathlib
assert os.uname().machine=='aarch64', 'Unsupported architecture'
compatible=pathlib.Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
if b'radxa,cubie-a7a' in compatible:
    print('cubie-a7a')
else:
    p=pathlib.Path('/etc/labrix/board-profile.json')
    assert not p.is_symlink(), 'Invalid board profile'
    record=json.loads(p.read_text())
    assert record.get('schema')==1 and record.get('confirmed') is True and record.get('board_id')=='cl3566-a-e' and b'rockchip,rk3566' in compatible, 'Unsupported or unconfirmed board'
    print('cl3566-a-e')
PYBOARD
)
/usr/bin/python3 -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' || { echo 'Install python3-cryptography first'; exit 1; }
/usr/bin/python3 -c 'import sys; from cryptography.hazmat.primitives import serialization; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey; assert isinstance(serialization.load_pem_public_key(open(sys.argv[1],"rb").read()),Ed25519PublicKey)' "$1"
install -d -m 0755 /etc/labrix-updates
if [ -f /etc/labrix-updates/signing.pub.pem ]; then
 cmp -s "$1" /etc/labrix-updates/signing.pub.pem || { echo 'Trust key change requires separate service procedure'; exit 1; }
fi
install -m 0644 "$1" /etc/labrix-updates/signing.pub.pem
/usr/bin/python3 -c 'import pathlib,secrets,os; p=pathlib.Path("/etc/labrix-updates/agent.token"); p.exists() or p.write_text(secrets.token_hex(32)); os.chmod(p,0o600)'
printf '%s\n' "$board" > /etc/labrix-updates/hardware
install -m 0644 deploy/sammoy2-software-updates.service /etc/systemd/system/
install -m 0644 deploy/sammoy2-update-cleanup.service deploy/sammoy2-update-cleanup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sammoy2-software-updates.service sammoy2-update-cleanup.timer
echo 'Updater installed. No application update was started.'
