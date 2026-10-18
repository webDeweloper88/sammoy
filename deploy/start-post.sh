#!/bin/sh
set -eu
cd /opt/sammoy/sammoy2
profile='full'
[ ! -f .hardware-profile ] || profile=$(cat .hardware-profile)
case "$profile" in
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
