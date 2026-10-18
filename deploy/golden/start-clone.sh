#!/bin/sh
set -eu
cd /opt/sammoy/sammoy2
[ -f /var/lib/sammoy2/factory-pending ] || exit 0
[ -f .env ] && [ -f GOLDEN_TEMPLATE.json ] && [ -f .factory-identity-ready ]
# Images must already be loaded in the factory image; no builds or downloads here.
/opt/sammoy/sammoy2/deploy/start-post.sh
python3 - <<'PY'
import time,urllib.request
for attempt in range(30):
    try:
        urllib.request.urlopen("http://127.0.0.1/api/commissioning/status",timeout=3).close()
        break
    except Exception:
        if attempt == 29: raise
        time.sleep(1)
PY
rm /var/lib/sammoy2/factory-pending
