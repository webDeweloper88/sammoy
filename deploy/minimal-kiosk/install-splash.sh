#!/bin/sh
set -eu
[ "$(id -u)" = 0 ]
cd /opt/sammoy/sammoy2
state=/var/lib/sammoy2-minimal-kiosk
install -d -m 0700 "$state"
[ -e "$state/previous-plymouth-theme" ] || plymouth-set-default-theme > "$state/previous-plymouth-theme"
[ -e "$state/initrd-before-splash" ] || cp -p "/boot/initrd.img-$(uname -r)" "$state/initrd-before-splash"
install -d -m 0755 /usr/share/plymouth/themes/labrix
install -m 0644 deploy/minimal-kiosk/plymouth/labrix.plymouth /usr/share/plymouth/themes/labrix/
install -m 0644 apps/kiosk-ui/public/assets/theme2/brand/labrix_mark_L.png /usr/share/plymouth/themes/labrix/labrix.png
. /etc/sammoy2/display.conf
case "$KIOSK_ROTATION" in right) angle=1.57079632679;;left) angle=-1.57079632679;;inverted) angle=3.14159265359;;*) angle=0;;esac
sed "s/ROTATION/$angle/g" deploy/minimal-kiosk/plymouth/labrix.script >/usr/share/plymouth/themes/labrix/labrix.script
plymouth-set-default-theme labrix
update-initramfs -u -k "$(uname -r)"
lsinitramfs "/boot/initrd.img-$(uname -r)" | grep -q 'plymouth/themes/labrix/labrix.script'
printf '%s\n' 'LABRIX boot splash installed. Kernel and boot arguments unchanged.'
