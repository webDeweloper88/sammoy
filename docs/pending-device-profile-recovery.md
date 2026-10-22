# Pending device type and active profile startup

2026-10-21: post 1 still ran the commissioned dry_fog hardware map while
Owner selected a future wash request. Post 2 was offline for SD capture,
so the shared inventory change could not complete. After restart the
startup guard compared controller_device.requested to active type and
crashed repeatedly, causing HTTP 502 for login and all API routes.

Recovery: confirmed no funded open session or pending card job. Restored
only controller_device.type from wash to dry_fog with an audit event.
No balances, wallet policy, inventory, license or pulse journal were reset.

Fix: startup checks the applied hardware type and persisted commissioned
inventory. A different requested future type cannot invalidate the current
profile. The installer still applies new maps only after idle/OFF proofs.
Ten device-setup tests pass, including pending wash on valid fog profile
and rejection of a genuinely mismatched active inventory.

Installed primary engine-only patch. Current type remains dry_fog; wash
conversion is deferred until the standby returns. Windows SD capture and
post 2 remain untouched.

After the user returned the source SD and powered post 2 on, both posts were
confirmed idle and healthy. Using a temporary revoked-after-use Owner token,
requested wash on post 1 and saved only its inventory type to wash through the
replicated device-policy API; existing bonus/pause rules retained. Applied
installer profile with idle and all-output-OFF proofs. Both runtime APIs now
report wash, primary/standby roles remain 1/2. Primary helper map is the eight
wash outputs, all verified OFF; NFC and Modbus online. No test relay activation,
financial reset or changes to the Windows source image were made.


Follow-up: the historic nfc-relay target map explicitly disabled bill_acceptor,
so conversion also disabled cash despite a healthy input. Fixed installer to
preserve the running bill wiring/enabled configuration before changing maps;
3 focused regression tests pass. Restored enabled=true and selected level
reader on idle primary with engine stopped, updated helper to previously
validated level-reader code. Original stream/counter 46475 retained; no
credit changes, cash filter ready and no fault afterward. No relay test
was performed. Windows hash/copy process is independent and untouched.
