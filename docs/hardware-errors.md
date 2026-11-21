# Hardware errors and peripheral warnings

Implemented 21 November 2026. The engine exposes `hardwareErrorCode`, `hardwareWarnings`, `nfcReady`, `billInputReady`, and technical `lastError`/`billInputFault` details. Customer messages are localized in Uzbek, Russian, Kazakh, and Kyrgyz; raw exception details are not shown to customers.

Critical codes distinguish lost Modbus connection, unavailable helper, stale polling, invalid protocol/profile, unconfirmed outputs, controller restart/safety trip, cash accounting failure, and unexpected control errors. They retain existing OFF attempts, preserve remaining runtime credit, and clear armed/active mode so restored connectivity cannot restart a wash automatically. OFF cannot be guaranteed when the physical bus or host is unavailable; see watchdog audit.

NV9 listener/filter faults disable the cash method and display a warning without rejecting healthy I/O proof. NFC offline/error/HTTP failures disable the card method and display a warning without stopping an otherwise healthy paid wash. RFID HTTP polling uses a separate pool with a 250 ms timeout to avoid spending the control lease waiting for an optional peripheral. QR availability retains its independent license/internet/configuration checks. Peripheral warnings occupy space inside the existing program area rather than adding an uncontrolled screen grid row.

Durable NV9 capture still runs even when its listener is offline: already confirmed journal pulses must not disappear. Invalid durable counters, counter rollback, or database accounting errors remain critical; uncertain cash is not silently credited or discarded. Existing transactional cursor/recovery handling is unchanged. Software cannot physically prevent banknote acceptance without an acceptor inhibit interface.

Fault/warning transitions and recovery are logged with UTC timestamps in wash-engine container logs. Repeated identical fault polling does not repeatedly emit transition messages. These messages are not new rows in the database system_events table.

Verification: 68 engine tests passed, including paid operation during each/both peripheral failures, NFC HTTP failure, I/O loss preserving credit with no automatic resumption, helper loss, filter recovery, cash accounting failure, and durable capture while listener is offline. Four-language message mapping checks passed; production Vue build passed (existing bundle-size warning). No browser visual test or new physical unplug test was performed during deployment.

Deployment: errors-20261121 engine/UI images; io-helper and electrical mapping unchanged. Correct per-host Compose overrides retained, no host reboot, backup or financial reset. Radxa post2 had 9,442 sum before and after graceful engine update, with outputs OFF; its PN532 reports an actual I2C error, now exposed as a noncritical warning. CL3566 post1 deployment result is recorded in deployed-state document.
