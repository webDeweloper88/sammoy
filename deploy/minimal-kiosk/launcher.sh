#!/bin/sh
set -eu
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/kiosk/.Xauthority}
export XCURSOR_THEME=SAMMOY-Invisible
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
until xset q >/dev/null 2>&1 && [ -f "$XDG_RUNTIME_DIR/sammoy2-display-ready" ]; do sleep 1; done
install -d -m 0700 /home/kiosk/.config/sammoy2-chromium
exec /usr/local/chromium/bin/chrome --kiosk --no-first-run --no-default-browser-check \
 --disable-session-crashed-bubble --disable-features=Translate \
 --disk-cache-size=67108864 --media-cache-size=33554432 \
 --user-data-dir=/home/kiosk/.config/sammoy2-chromium \
 file:///usr/local/share/labrix-kiosk/boot.html
