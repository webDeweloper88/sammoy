# Admin — SAMMOY2

On the panel open `/login`; from the local network open
`http://10.10.10.8/login` (use the new IP if the address changes). Port 80 serves
the UI; local panel access at `127.0.0.1:8081` remains available. Sign in with the web Admin account, and complete the required
first-login password change. Admin opens `/admin/diagnostics`; Owner cannot access
Admin operations. Linux/sudo credentials are separate from web accounts.

The landscape 1920×1080 interface supports RU/UZ/EN, persistent light/dark theme,
onscreen keyboard and unsaved-change confirmation.

## Pages

- **Diagnostics**: Modbus link, eight raw/logical inputs, eight relay outputs,
  active-low DI3 trigger, PN532 firmware/last card, NV9 pulses/listener,
  temperature and free disk. Refresh interval: two seconds. Missing/stale Modbus
  readings are unknown, not reported as confirmed OFF.
- **Connection**: Ethernet/Wi-Fi, DHCP/static IPv4, optional gateway and DNS,
  WPA2/WPA3 Personal, Wi-Fi scan; activation server, site identity, post number,
  Click and licence settings. Empty site-key input retains the existing key.
- **Maintenance**: diagnostic JSON download with UID/secret fields removed,
  NV9 pulse value, real-input restoration, licence sync/offline code, Click sync,
  paginated event log and read-only unclaimed recovery-credit list.

## Service actions

Relay tests require an empty, finished session, live Modbus, all eight outputs OFF
and explicit operator confirmation. `io-helper` owns the one-second ON/OFF pulse,
so closing the browser does not cancel the OFF operation. This is software timing,
not an independent hardware watchdog. Hardware readback is required before success.

“All outputs OFF” uses the existing SAMMOY2 WEB PAUSE behavior and verifies all
outputs. It does not erase credit or substitute the old project's pause rules.
There is no balance-reset/database-reset control on these pages.

## Network changes

Host NetworkManager is accessed through a root-only Unix socket mounted into
wash-engine. No network administration HTTP port is exposed on the LAN.
`sudo sh /opt/sammoy/sammoy2/deploy/install-admin-network.sh` installs the host
service without changing a network profile.

Applying creates an in-memory connection and a 90-second NetworkManager checkpoint
for the selected physical interface. Confirm on the panel after checking the new
connection; otherwise NetworkManager rolls it back. Confirmation is rejected if
the new connection is not active or fewer than ten seconds remain. Passwords are
not returned to the browser. Wi-Fi password is required when applying a profile.
An isolated Ethernet LAN can use static IPv4 without a default gateway.

Report API listens on port 8091 across host IPv4 interfaces with its existing bearer
key requirement, so changing the host IP does not leave Docker bound to an old IP.
Post discovery derives the active LAN from the network service, with the existing
REPORT_LAN_CIDR fallback for older installations. Discovery supports private IPv4
subnets of /24 or smaller. Actual multi-post discovery still requires activated
site identity and shared report credentials.

## Verification on 2026-10-02

87 isolated tests passed: wash-engine/auth 42, output pulse/RFID 9, host network 9,
reporting 27. Browser suites passed for Admin, Owner, touch login/password changes
and installation. Relay pulses and network apply/confirm/rollback were mocked;
real output activation and real network reconfiguration were not performed.

Admin/UI, wash-engine, reporting and the host network service were deployed.
USB–RS485 is currently disconnected; `/dev/ttyUSB0` is absent and io-helper cannot
start. The user confirmed the adapter cannot be connected now. Physical Modbus,
PN532 through io-helper and NV9 integration need verification after reconnection.
This is not a production hardware acceptance test.

After reconnecting the adapter, from `/opt/sammoy/sammoy2` run:

```sh
sudo docker compose up -d --no-deps io-helper
```

Then inspect Diagnostics before any relay test. Existing client credit must be
handled using the agreed session rules; do not zero it merely to unlock service
settings. After restart, the existing recovery timeout rule closed session 8 and preserved
1744 sum in recovery_credits (id 1, unclaimed). Current session balance is 0.
No funds were manually reset or reassigned, and no output activation was requested.

## Update — 2026-10-03

Admin and Owner are now separate in navigation and API authorization. Admin has
Diagnostics, Connection, License, Click, Maintenance and its own Account. Detailed
license and Click controls moved from Maintenance to their dedicated pages.
Connection also displays board/microSD identity. Diagnostics shows the last RFID
processing result, which is no longer lost on the next reader heartbeat.
Maintenance includes storage monitoring and cleanup status.

See [retention and 32 GB storage policy](storage.md). Financial history is retained
for 12 calendar months, events for one month, and technical journals have a shared
256 MB budget. Current card balances and unclaimed recovery credit never expire.
