#!/bin/sh
# Run on the dedicated factory OS, after copying the exported template.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Root required'; exit 1; }
cd /opt/sammoy/sammoy2
chmod 0755 /opt/sammoy/sammoy2
[ -f GOLDEN_TEMPLATE.json ] || { echo 'Exported template required'; exit 1; }
[ ! -e .env ] || { echo 'Already initialized; refusing factory preparation'; exit 1; }
[ ! -d data ] || { echo 'Data directory exists; refusing factory preparation'; exit 1; }
install -d -m 0700 /var/lib/sammoy2
install -m 0644 deploy/golden/sammoy2-factory-identity.service /etc/systemd/system/
install -m 0644 deploy/golden/sammoy2-factory-app.service /etc/systemd/system/
# Requires (in addition to Before) prevents Docker/SSH starting after identity failure.
for unit in docker.service ssh.service ssh.socket; do
    install -d -m 0755 "/etc/systemd/system/$unit.d"
    cat >"/etc/systemd/system/$unit.d/sammoy2-factory.conf" <<'EOF'
[Unit]
Requires=sammoy2-factory-identity.service
After=sammoy2-factory-identity.service
EOF
done
touch /var/lib/sammoy2/factory-pending
systemctl daemon-reload
systemctl enable sammoy2-factory-identity.service sammoy2-factory-app.service
printf '%s\n' 'Factory services installed. No services started and no active data erased.'
