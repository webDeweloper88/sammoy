#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo'; exit 1; }
cd /opt/sammoy/sammoy2
mkdir -p /etc/labrix
install -m 0644 deploy/sammoy2-admin-system.service /etc/systemd/system/sammoy2-admin-system.service
systemctl daemon-reload
systemctl enable --now sammoy2-admin-system.service
systemctl is-active --quiet sammoy2-admin-system.service
echo 'System maintenance service installed; no power or reset action was executed.'
