#!/bin/sh
set -eu
[ "$(id -u)" = 0 ]
cd /opt/sammoy/sammoy2
command -v openbox >/dev/null
command -v xrandr >/dev/null
state=/var/lib/sammoy2-minimal-kiosk
install -d -m 0700 "$state"
[ -e "$state/original-autologin.conf" ] || cp /etc/sddm.conf.d/10-sammoy-autologin.conf "$state/original-autologin.conf"
install -d -m 0755 /etc/sammoy2 /etc/systemd/system/sammoy2-kiosk.service.d /usr/local/share/labrix-kiosk
# Keep an existing per-device display configuration on repeat installs.
if [ ! -f /etc/sammoy2/display.conf ]; then
 DISPLAY=:0 XAUTHORITY=/home/kiosk/.Xauthority python3 - <<'PY'
import subprocess,shlex
from pathlib import Path
lines=subprocess.check_output(['xrandr','--current'],text=True).splitlines()
line=next(x for x in lines if ' connected primary ' in x)
head=line.split(' (',1)[0].split()
rotation=next((x for x in head[3:] if x in ('left','right','normal','inverted')),'normal')
Path('/etc/sammoy2/display.conf').write_text('KIOSK_OUTPUT='+shlex.quote(head[0])+'\nKIOSK_ROTATION='+shlex.quote(rotation)+'\n')
PY
fi
install -m 0644 deploy/minimal-kiosk/openbox.xml /etc/sammoy2/openbox.xml
install -m 0644 deploy/minimal-kiosk/labrix-kiosk.desktop /usr/share/xsessions/labrix-kiosk.desktop
install -m 0644 deploy/minimal-kiosk/boot.html /usr/local/share/labrix-kiosk/boot.html
install -d -m 0755 /etc/systemd/system/hdmi-toggle-once.service.d
install -m 0644 deploy/minimal-kiosk/hdmi-orientation.conf /etc/systemd/system/hdmi-toggle-once.service.d/90-labrix-orientation.conf
install -m 0644 apps/kiosk-ui/public/assets/theme2/brand/labrix_mark_L.png /usr/local/share/labrix-kiosk/labrix.png
cat >/etc/sddm.conf.d/90-labrix-minimal.conf <<'CONF'
[Autologin]
User=kiosk
Session=labrix-kiosk.desktop
Relogin=true
CONF
cat >/etc/systemd/system/sammoy2-kiosk.service.d/90-minimal.conf <<'CONF'
[Service]
ExecStart=
ExecStart=/opt/sammoy/sammoy2/deploy/minimal-kiosk/launcher.sh
CONF
systemctl daemon-reload
printf '%s\n' 'Minimal session prepared. Restart the display manager to apply. Rollback: deploy/minimal-kiosk/rollback.sh'
