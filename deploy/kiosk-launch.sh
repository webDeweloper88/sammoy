#!/bin/sh
set -eu
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/kiosk/.Xauthority}
export XCURSOR_THEME=SAMMOY-Invisible
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
# Wait for the existing X11 session; never rotate display or modify input devices.
until xset q >/dev/null 2>&1; do sleep 2; done
until curl -fsS http://127.0.0.1/api/commissioning/state >/dev/null; do sleep 2; done
xset s off
xset -dpms
xset s noblank
install -d -m 0700 /home/kiosk/.config/sammoy2-chromium
exec /usr/local/chromium/bin/chrome --kiosk --no-first-run --no-default-browser-check \
  --disable-session-crashed-bubble --disable-features=Translate \
  --user-data-dir=/home/kiosk/.config/sammoy2-chromium \
  http://127.0.0.1/launch
