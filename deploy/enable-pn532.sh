#!/bin/sh
# Run on the Radxa host: sudo sh /opt/sammoy/sammoy2/deploy/enable-pn532.sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo." >&2
    exit 1
fi
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
test -c /dev/i2c-7
test -f /sys/bus/platform/devices/2517000.twi/twi_mode
docker compose config --quiet
# Build before restarting the running services.
docker compose build io-helper wash-engine
install -m 644 deploy/sammoy2-pn532-i2c.service /etc/systemd/system/sammoy2-pn532-i2c.service
systemctl daemon-reload
systemctl enable --now sammoy2-pn532-i2c.service
docker compose up -d --no-deps io-helper wash-engine
python3 - <<'PY'
import json
import time
import urllib.request

last_error = "No response"
for attempt in range(45):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/rfid/latest", timeout=2) as response:
            state = json.load(response)
        if state.get("online"):
            print("PN532 ONLINE:", json.dumps(state, ensure_ascii=False))
            break
        last_error = state.get("last_error") or str(state)
    except Exception as exc:
        last_error = str(exc)
    time.sleep(1)
else:
    raise SystemExit("PN532 is not online: " + last_error)
PY
