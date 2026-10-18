#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo'; exit 1; }
cd /opt/sammoy/sammoy2
install -d -m 0755 /etc/systemd/journald.conf.d
install -m 0644 deploy/sammoy2-journald.conf /etc/systemd/journald.conf.d/sammoy2.conf
install -m 0644 deploy/sammoy2-log-retention.service deploy/sammoy2-log-retention.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart systemd-journald
systemctl enable --now sammoy2-log-retention.timer
systemctl start sammoy2-log-retention.service
journalctl --disk-usage
