#!/bin/sh
set -eu
runtime=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
ready=$runtime/sammoy2-display-ready
rm -f "$ready"
cursor_pid=
cleanup(){ rm -f "$ready"; [ -z "$cursor_pid" ] || kill "$cursor_pid" 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM
# Display geometry is device configuration, not a desktop preference.
. /etc/sammoy2/display.conf
xrandr --output "$KIOSK_OUTPUT" --rotate "$KIOSK_ROTATION"
xset s off
xset -dpms
xset s noblank
xsetroot -solid '#071824'
printf 'Xcursor.theme: SAMMOY-Invisible\nXcursor.size: 24\n' | xrdb -merge
/usr/bin/python3 /opt/sammoy/sammoy2/deploy/minimal-kiosk/hide-cursor.py &
cursor_pid=$!
touch "$ready"
/usr/bin/openbox --config-file /etc/sammoy2/openbox.xml
