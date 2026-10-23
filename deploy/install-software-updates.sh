#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo'; exit 1; }
cd /opt/sammoy/sammoy2
[ "$#" = 1 ] && [ -f "$1" ] || { echo 'Usage: sudo deploy/install-software-updates.sh trusted-public-key.pem'; exit 1; }
/usr/bin/python3 -c 'import pathlib,os; assert b"radxa,cubie-a7a" in pathlib.Path("/proc/device-tree/compatible").read_bytes().split(b"\0") and os.uname().machine=="aarch64", "Unsupported board"'
/usr/bin/python3 -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' || { echo 'Install python3-cryptography first'; exit 1; }
/usr/bin/python3 -c 'import sys; from cryptography.hazmat.primitives import serialization; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey; assert isinstance(serialization.load_pem_public_key(open(sys.argv[1],"rb").read()),Ed25519PublicKey)' "$1"
install -d -m 0755 /etc/labrix-updates
if [ -f /etc/labrix-updates/signing.pub.pem ]; then
 cmp -s "$1" /etc/labrix-updates/signing.pub.pem || { echo 'Trust key change requires separate service procedure'; exit 1; }
fi
install -m 0644 "$1" /etc/labrix-updates/signing.pub.pem
/usr/bin/python3 -c 'import pathlib,secrets,os; p=pathlib.Path("/etc/labrix-updates/agent.token"); p.exists() or p.write_text(secrets.token_hex(32)); os.chmod(p,0o600)'
printf '%s\n' cubie-a7a > /etc/labrix-updates/hardware
install -m 0644 deploy/sammoy2-software-updates.service /etc/systemd/system/
install -m 0644 deploy/sammoy2-update-cleanup.service deploy/sammoy2-update-cleanup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sammoy2-software-updates.service sammoy2-update-cleanup.timer
echo 'Updater installed. No application update was started.'
