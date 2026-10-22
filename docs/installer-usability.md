# Installer usability — 2026-10-20

The standby's policy read returned the primary's `local_post`. This enabled its
global form; posting it to the standby raised an uncaught `WalletUnavailable`
before the endpoint's exception handler, producing HTTP 500. Policy reads now
combine the authenticated primary policy with the requesting node's identity.
Standby controls are read-only with a link to the primary installer. Writes to
the standby return 409; unavailable primary reads return 503, not traceback 500.

Initial wallet setup now reads the existing network interface/address/prefix,
chooses the interface matching the browser's address (or connected Ethernet,
then Wi-Fi for a local kiosk), fills this device's own address, and supplies a
short numeric final-octet field. The rest of the HTTP address remains visible.
Full address input remains available. The device number is explicitly distinct
from the address: post 2 may be `10.10.10.7`, not necessarily `.2`.

Subnet checks use the actual prefix, including non-/24 networks. Network and
broadcast addresses and out-of-subnet choices are rejected when a prefix is
known. Duplicate endpoints are rejected in both UI and backend (default port 80
and trailing slash normalize to the same endpoint). Adding a row chooses the
next unused station number. Default primary/standby are 1/2, while existing
configured numbers are retained.

Activation accepts typing/paste without separators, uppercases the 16 characters
and inserts four-character groups. The caret and deleting across a separator
are handled, including the on-screen keyboard. Signed offline licence tokens
are unrelated and are not rewritten. Short IP inputs use an integer keypad.

Management and installer pages retain native touch panning. X11 panels exposed
as mouse drags have an additional background-only drag/inertia fallback. Inputs,
buttons, links, selects and the keyboard are excluded; a drag cannot turn into
an accidental button click. Reduced-motion users receive no extra inertia.
Customer wash/relay controls never register this fallback. Horizontal panning
is retained for management tables/navigation.

The initial installer also exposes synchronization on the primary, using a
commissioning-access-protected endpoint delegating to the established wallet
synchronizer. It does not expose promotion/failover or financial recovery there.

## Verification

- 257 engine unit tests pass, including local-vs-primary identity, standby write
  refusal, unavailable reads and duplicate peer endpoint rejection.
- Activation/subnet helper tests, full installer browser flow, touch-only login
  at 1080×1920 and 1920×1080, and mouse/native-touch scrolling tests pass.
- Live reads on both devices return the correct local identity. Live backup
  write returns 409 without modifying policy. No HTTP 500 or JavaScript errors
  were observed in the completed live installer browser checks.
- User confirmed post 1 is dry fog and post 2 is wash. Applied those hardware
  profiles, retaining the configured Modbus/NV9/PN532 settings. Both have I/O
  ready, no device-profile mismatch, bill input ready, and zero customer credit.
- Existing wallet synchronization completed: three operations reconciled and
  version-2 state/journal proof accepted; standby readiness is true.

The installer was not automatically completed and no customer service relay
test was triggered by these browser checks. Changes have not been pushed.
