#!/bin/sh
set -eu
cd /opt/sammoy/sammoy2
# Existing deployments retain the legacy launcher. Invalid records fail closed.
board=$(python3 deploy/board_runtime.py selected)
if [ "$board" = cl3566-unconfirmed ]; then
    exec python3 deploy/board_runtime.py factory
fi
if [ "$board" = cl3566-a-e ]; then
    exec python3 deploy/board_runtime.py start
fi
profile='full'
[ ! -f .hardware-profile ] || profile=$(cat .hardware-profile)
case "$profile" in
  dry-fog)
    if [ -c /dev/ttyUSB0 ] && [ -c /dev/gpiochip0 ] && [ -c /dev/i2c-7 ]; then
      exec docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml -f docker-compose.dry-fog.yml up -d --no-build --pull never --wait --wait-timeout 180
    fi ;;
  relay-only)
    if [ -c /dev/ttyUSB0 ] && [ -c /dev/gpiochip0 ]; then
      exec docker compose -f docker-compose.yml -f docker-compose.relay-only.yml up -d --no-build --pull never --wait --wait-timeout 180
    fi ;;
  nfc-relay)
    if [ -c /dev/ttyUSB0 ] && [ -c /dev/gpiochip0 ] && [ -c /dev/i2c-7 ]; then
      exec docker compose -f docker-compose.yml -f docker-compose.nfc-relay.yml up -d --no-build --pull never --wait --wait-timeout 180
    fi ;;
  full|factory-only) ;;
  *) echo 'Unknown hardware profile'; exit 1 ;;
esac
# Factory UI must remain reachable when peripheral devices are not installed.
# This does not turn on simulation or report hardware as ready.
if [ "$profile" = full ] && [ -c /dev/gpiochip0 ] && [ -c /dev/ttyUSB0 ] && [ -c /dev/i2c-7 ]; then
    exec docker compose up -d --no-build --pull never --wait --wait-timeout 180
fi
printf '%s\n' 'Peripheral devices missing: starting commissioning UI without io-helper.'
exec docker compose -f docker-compose.yml -f docker-compose.factory.yml up -d --no-build --pull never --wait --wait-timeout 180
