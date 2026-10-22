#!/bin/sh
set -eu
state=/var/lib/sammoy2-minimal-kiosk
[ -d "$state" ] || exit 1
[ -x /usr/bin/startplasma-x11 ] || { echo "KDE packages were removed; restore them before desktop rollback. Minimal kiosk configuration is unchanged."; exit 1; }
systemctl stop sammoy2-kiosk.service
rm -f /etc/sddm.conf.d/90-labrix-minimal.conf
rm -f /etc/systemd/system/sammoy2-kiosk.service.d/90-minimal.conf
systemctl daemon-reload
systemctl restart display-manager.service
systemctl start sammoy2-kiosk.service
