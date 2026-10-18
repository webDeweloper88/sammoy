#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo'; exit 1; }
cd /opt/sammoy/sammoy2
python3 -c 'import dbus'
systemctl is-active --quiet NetworkManager
install -m 0644 deploy/sammoy2-admin-network.service /etc/systemd/system/sammoy2-admin-network.service
systemctl daemon-reload
systemctl enable --now sammoy2-admin-network.service
systemctl is-active --quiet sammoy2-admin-network.service
echo 'Admin network service installed. Network profiles were not changed.'
