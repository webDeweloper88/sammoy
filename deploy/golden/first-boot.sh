#!/bin/sh
# Installed on a dedicated factory card; never run on an activated post.
set -eu
APP=/opt/sammoy/sammoy2
MARKER=/var/lib/sammoy2/factory-pending
[ -f "$MARKER" ] || exit 0
[ -f "$APP/GOLDEN_TEMPLATE.json" ]
# A preexisting application identity is never silently replaced.
if [ ! -f "$APP/.env" ]; then
    python3 "$APP/deploy/golden/identity.py" "$APP"
fi
[ -f "$APP/.factory-identity-ready" ] || { echo "Incomplete identity initialization; service intervention required"; exit 1; }
[ -s /etc/machine-id ] || systemd-machine-id-setup
ssh-keygen -A
suffix="$(tr -d ':' </sys/class/net/eth0/address | tail -c 7)"
[ -n "$suffix" ]
hostname="labrix-${suffix}"
printf '%s\n' "$hostname" >/etc/hostname
hostname "$hostname"
python3 - "$hostname" <<'PY'
import pathlib,sys
p=pathlib.Path('/etc/hosts')
lines=[line for line in p.read_text().splitlines() if not line.startswith('127.0.1.1')]
p.write_text('\n'.join(lines)+'\n127.0.1.1\t'+sys.argv[1]+'\n')
PY
# Docker starts only after this service succeeds. A failed attempt retains marker.
sync
