# Watchdog verification, 21 November 2026

Checked Radxa 10.10.10.8 and CL3566 10.10.10.26. Both had healthy Modbus, no-credit idle wash state, and eight outputs OFF.

On both hosts systemd reports RuntimeWatchdogUSec=10s and PID 1 holds /dev/watchdog0 open. This confirms configuration and ownership, not an actual hardware-reset test. The vendor kernels expose a reduced watchdog sysfs interface without identity/state/timeout files. No watchdog device was separately opened, and neither host was rebooted.

On each host the wash-engine container was paused for 3.2 seconds and resumed in a finally block. The io-helper lease expired while the engine was suspended; Modbus stayed healthy and outputs stayed OFF. After resuming, the lease recovered and all outputs remained OFF. This idle test does not demonstrate de-energizing a previously energized relay, preservation of paid credit, or behavior during a full host hang.

21 existing controller lease and output safety unit tests passed in the deployed helper image with current source mounted.

The helper watchdog checks every 50 ms and attempts output shutdown after the 2-second controller lease expires. It depends on a functioning host/helper and working RS485. Docker restart: unless-stopped restarts exited containers; it does not itself detect a frozen live process. The systemd hardware watchdog is fed by PID 1, not by the wash application's health.

No documented autonomous communication-loss shutdown was identified in the supplied I/O instructions or current driver. This is unverified, not proof of absence. Vendor pulse/flash modes are not equivalent to a communication watchdog. Do not write undocumented registers to a live module.

Remaining hardware work: obtain the exact module model/firmware manual and verify a communication watchdog, or install an independent pulse-monitor relay in the equipment enable circuit, designed by the equipment electrician. Its pulses must depend on application and I/O health. Choose its timeout against actual pump/valve stopping requirements. Validate energized-output shutdown on an isolated bench, RS485 loss, helper/host hang, and manual-only resumption. Software restart alone cannot guarantee external relay shutdown during host or bus failure.
