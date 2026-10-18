#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo.' >&2; exit 1; fi
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$project_dir" != /opt/sammoy/sammoy2 ]; then echo 'Adjust the service paths for this installation.' >&2; exit 1; fi
install -d -m 700 /var/backups/sammoy2
install -m 644 "$project_dir/deploy/sammoy2-backup.service" /etc/systemd/system/sammoy2-backup.service
install -m 644 "$project_dir/deploy/sammoy2-backup.timer" /etc/systemd/system/sammoy2-backup.timer
systemctl daemon-reload
systemctl enable --now sammoy2-backup.timer
