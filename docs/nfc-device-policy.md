# NFC device policy

PN532 activation metadata (UID, SAK and raw ATQA bytes) is read from a single
InListPassiveTarget response using the existing Adafruit 2.4.9 Linux I2C transport.
Ordinary ISO14443A cards do not need registration. No UID allowlist is introduced.

Before any wallet freeze, card lookup or session/financial operation, wash-engine
rejects ISO-DEP (`sak & 0x20`) and events without valid SAK/ATQA. The kiosk displays
an unsupported NFC message in the customer's selected language. Admin diagnostics
show the same result. Existing funds and unfinished transfers are preserved;
rejected scans do not resolve or cancel transfers.

This is a protocol filter, not universal phone detection or authentication.
Physical ISO-DEP cards (including DESFire) are rejected too. Phones emulating a
non-ISO-DEP card and cloned UIDs are not covered. Test the intended physical cards
and phone before customer use. Existing funds associated with rejected devices
need a separate operator recovery procedure; do not re-enable automatic phone UID
wallet transfers to recover them.

Deployment must update io-helper and wash-engine together: the backend rejects
legacy UID-only events. Install the matching kiosk interface too. Restart only
while the station is idle with no balance, card transfer or requested output.
The GPIO process reader and existing filter configuration must be preserved.
Previously exported golden IMG files are not updated by these source changes.
