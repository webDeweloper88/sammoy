#!/bin/sh
# Installer action, never called by a customer's screen.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.' >&2; exit 1; }
cd /opt/sammoy/sammoy2
# Serialize direct installer commands and requests through the maintenance agent.
mkdir -p /run/sammoy2-admin
exec 9>/run/sammoy2-admin/profile.lock
flock -n 9 || { echo 'Another profile operation is running' >&2; exit 1; }
engine_stopped=0
recover() {
  result=$?
  trap - EXIT HUP INT TERM
  if [ "$result" -ne 0 ] && [ "$engine_stopped" = 1 ]; then
    # Restore API access; never reset data, counters or force a relay ON.
    docker start sammoy2-wash-engine >/dev/null 2>&1 || true
  fi
  exit "$result"
}
trap recover EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
selected=$(python3 - <<'PY'
import json,urllib.request
get=lambda path:json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8090'+path,headers={'X-Commissioning-Client-IP':'127.0.0.1'}),timeout=5))
s=get('/api/wash/state')['state']
if any(s.get(k) for k in ('creditSum','activeSessionId','activeMode','armedMode','requestedOutput','walletTransferPending','walletCashHeld','vipRemainingSeconds')):raise SystemExit('Finish the session and card operation first')
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
if [ "$previous" = factory-only ]; then
  restore=nfc-relay
  [ ! -f .hardware-profile.before-factory-reset ] || restore=$(cat .hardware-profile.before-factory-reset)
  [ "$restore" != dry-fog ] || restore=nfc-relay
fi
if [ "$previous" = dry-fog ]; then
  restore=nfc-relay
  [ ! -f .hardware-profile.before-dry-fog ] || restore=$(cat .hardware-profile.before-dry-fog)
fi
# Board and service type are independent; never apply Cubie mounts to CL3566.
board=$(python3 deploy/board_runtime.py selected)
if [ "$board" = cl3566-a-e ]; then
  exec python3 deploy/apply-cl3566-profile.py
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
# A service-type switch changes relay names, not bill-input wiring/enabled state.
# Factory-only may have no helper; retain target defaults for a fresh install.
if [ "$(docker inspect --format '{{.State.Running}}' sammoy2-io-helper 2>/dev/null || true)" = true ]; then
  bill_config=$(docker exec sammoy2-io-helper python -c 'import json,yaml;print(json.dumps(yaml.safe_load(open("/config/io-map.yaml"))["bill_acceptor"]))')
  if [ "$selected" = dry_fog ]; then
    bill_target=config/io-map.dry-fog.yaml
  elif [ "$restore" = full ]; then
    bill_target=config/io-map.yaml
  else
    bill_target=config/io-map.nfc-relay.yaml
  fi
  python3 deploy/preserve-bill-config.py "$bill_target" "$bill_config"
fi
engine_stopped=1
docker stop sammoy2-wash-engine >/dev/null
# Factory reset deliberately leaves the helper stopped. Start it with the
# chosen map while the engine is stopped; helper boot guarantees outputs OFF.
if [ "$previous" = factory-only ]; then
  if [ "$selected" = dry_fog ]; then
    docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml -f docker-compose.dry-fog.yml up -d --no-build --pull never --no-deps --wait --wait-timeout 120 io-helper
  elif [ "$restore" = full ]; then
    docker compose up -d --no-build --pull never --no-deps --wait --wait-timeout 120 io-helper
  else
    docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml up -d --no-build --pull never --no-deps --wait --wait-timeout 120 io-helper
  fi
fi
# Engine must leave every physical output OFF before helper changes its map.
docker exec sammoy2-io-helper python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/io")); assert d.get("modbus_ok") is True and len(d["outputs"])==8 and all(v is False for v in d["outputs"].values()), "OFF proof missing"'
if [ "$selected" = dry_fog ]; then
  [ "$previous" = dry-fog ] || printf '%s\n' "$previous" > .hardware-profile.before-dry-fog
  printf '%s\n' dry-fog > .hardware-profile
  docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml -f docker-compose.dry-fog.yml up -d --no-build --pull never --no-deps --wait --wait-timeout 120 io-helper wash-engine
elif [ "$restore" = full ]; then
  printf '%s\n' full > .hardware-profile
  docker compose up -d --no-build --pull never --no-deps --wait --wait-timeout 120 io-helper wash-engine
else
  printf '%s\n' nfc-relay > .hardware-profile
  docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml up -d --no-build --pull never --no-deps --wait --wait-timeout 120 io-helper wash-engine
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
