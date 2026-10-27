#!/bin/sh
# Fixed host prerequisites, only on an explicitly confirmed CL3566.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo' >&2; exit 1; }
cd /opt/sammoy/sammoy2
[ "$(python3 deploy/board_runtime.py selected)" = cl3566-a-e ] || { echo 'CL3566 confirmation required' >&2; exit 1; }
# Profile switching preserves YAML bill settings on the host.
python3 -c 'import yaml' || { echo 'Install python3-yaml before commissioning' >&2; exit 1; }
command -v docker >/dev/null
docker compose version >/dev/null
backup=/var/lib/labrix/cl3566-host-backup
mkdir -p "$backup"
chmod 700 "$backup"
# Preserve the first choice; do not flush or replace existing firewall rules.
if [ ! -f "$backup/iptables-alternatives.txt" ]; then
 update-alternatives --query iptables > "$backup/iptables-alternatives.txt"
 iptables-save > "$backup/iptables-rules.txt"
fi
# This vendor kernel has legacy NAT but lacks nft MASQUERADE.
if zcat /proc/config.gz | grep -q '^# CONFIG_NFT_MASQ is not set$'; then
 zcat /proc/config.gz | grep -q '^CONFIG_NETFILTER_XT_TARGET_MASQUERADE=y$'
 update-alternatives --set iptables /usr/sbin/iptables-legacy
fi
install -m 0644 deploy/labrix-cl3566-io5-input.service /etc/systemd/system/labrix-cl3566-io5-input.service
mkdir -p /etc/systemd/system/docker.service.d
if [ -f /etc/systemd/system/docker.service.d/labrix-input.conf ] && [ ! -f "$backup/docker-input.conf" ]; then
 cp /etc/systemd/system/docker.service.d/labrix-input.conf "$backup/docker-input.conf"
fi
cat > /etc/systemd/system/docker.service.d/labrix-input.conf <<'UNIT'
[Unit]
Requires=labrix-cl3566-io5-input.service
After=labrix-cl3566-io5-input.service
UNIT
systemctl daemon-reload
systemctl enable --now labrix-cl3566-io5-input.service
systemctl enable docker
systemctl reset-failed docker.service docker.socket
systemctl start docker
printf '%s\n' 'CL3566 host prerequisites ready; application stack not started.'
