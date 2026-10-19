#!/bin/sh
# Installer action, never called by a customer's screen.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.' >&2; exit 1; }
cd /opt/sammoy/sammoy2
selected=$(python3 - <<'PY'
import json,urllib.request
get=lambda path:json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8090'+path,headers={'X-Commissioning-Client-IP':'127.0.0.1'}),timeout=5))
s=get('/api/wash/state')['state']
if any(s.get(k) for k in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld')):raise SystemExit('Finish the session and card operation first')
target=get('/api/commissioning/device')['requested']['type']
if target not in ('wash','dry_fog'):raise SystemExit('Unknown type')
c=get('/api/commissioning/wallet')['configuration']
if target=='dry_fog' and (not c.get('device_wallet_enabled') or c.get('device_types',{}).get(str(c['local_post']))!=target):raise SystemExit('Configure device types on the primary first')
print(target)
PY
)
previous=full
[ ! -f .hardware-profile ] || previous=$(cat .hardware-profile)
restore="$previous"
if [ "$previous" = dry-fog ]; then
  restore=nfc-relay
  [ ! -f .hardware-profile.before-dry-fog ] || restore=$(cat .hardware-profile.before-dry-fog)
fi
# Verify config/images before stopping the idle engine.
if [ "$selected" = dry_fog ]; then
  docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml -f docker-compose.dry-fog.yml config --quiet
elif [ "$restore" = full ]; then
  docker compose config --quiet
else
  docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml config --quiet
fi
docker image inspect sammoy2-wash-engine:latest >/dev/null
docker image inspect sammoy2-io-helper:latest >/dev/null
docker stop sammoy2-wash-engine >/dev/null
# Engine must leave every physical output OFF before helper changes its map.
docker exec sammoy2-io-helper python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/io")); assert d.get("modbus_ok") is True and len(d["outputs"])==8 and all(v is False for v in d["outputs"].values()), "OFF proof missing"'
if [ "$selected" = dry_fog ]; then
  [ "$previous" = dry-fog ] || printf '%s\n' "$previous" > .hardware-profile.before-dry-fog
  printf '%s\n' dry-fog > .hardware-profile
  docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml -f docker-compose.dry-fog.yml up -d --no-deps --wait --wait-timeout 120 io-helper wash-engine
elif [ "$restore" = full ]; then
  printf '%s\n' full > .hardware-profile
  docker compose up -d --no-deps --wait --wait-timeout 120 io-helper wash-engine
else
  printf '%s\n' nfc-relay > .hardware-profile
  docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml up -d --no-deps --wait --wait-timeout 120 io-helper wash-engine
fi
python3 - "$selected" <<'PY'
import json,sys,time,urllib.request
for _ in range(30):
 try:
  s=json.load(urllib.request.urlopen('http://127.0.0.1:8090/api/wash/state',timeout=3))['state']
  if s.get('deviceType')==sys.argv[1] and s.get('lastIoOk') and not s.get('creditSum') and not s.get('requestedOutput'):
   print('Device profile ready: '+sys.argv[1]);break
 except Exception:pass
 time.sleep(1)
else:raise SystemExit('Profile not ready; outputs must remain OFF. Review service logs.')
PY
