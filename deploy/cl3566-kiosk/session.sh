#!/bin/sh
set -eu
xrandr --output HDMI-1 --rotate right
xset s off
xset s noblank
xset -dpms
xsetroot -solid '#071824'
openbox --config-file /etc/labrix/openbox.xml &
wm=$!
/usr/bin/python3 /opt/sammoy/sammoy2/deploy/minimal-kiosk/hide-cursor.py &
cursor=$!
trap 'kill "$wm" "$cursor" 2>/dev/null || true' EXIT HUP INT TERM
/home/kiosk/.local/bin/labrix-kiosk.sh
