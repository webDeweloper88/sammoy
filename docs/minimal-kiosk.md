# Minimal kiosk on Radxa Cubie A7A

Trial target: **10.10.10.7 only**. No services, images, packages or runtime settings
on 10.10.10.8 were changed for this work. Repository edits are not deployed there.
Equipment type and site policy are not part of this change.

The verified stack is Debian 11, vendor kernel and graphics/input drivers, SDDM
autologin into a dedicated Openbox session, Chromium supervised by systemd,
NetworkManager, SSH and Docker. Plasma is not started. The existing touchscreen
Xorg transformation is retained; the output and rotation captured from Xrandr
are stored in `/etc/sammoy2/display.conf` (this board: HDMI-1, right).

## Startup

1. Firmware/bootloader screens are board-specific and are not modified.
2. Plymouth shows the LABRIX mark using the installed vendor kernel/initramfs.
3. SDDM enters `labrix-kiosk.desktop`; the session applies display geometry,
   disables blanking and starts the invisible-cursor XFixes client.
4. Chromium opens the local file `/usr/local/share/labrix-kiosk/boot.html` even
   if nginx and the backend are not up yet. The page retries local HTTP and
   enters `/launch` when the UI server responds.
5. The branded `/launch` retries the commissioning API. It enters `/wash` only
   for an explicitly completed installation, otherwise `/install`.

The cursor is hidden through XFixes for the X connection lifetime, independent
of KDE and browser CSS, with the existing transparent cursor theme retained.
Chromium disk cache is capped at 64 MiB; media cache at 32 MiB. systemd restarts
Chromium after a crash. This is crash recovery, not a renderer-hang watchdog.

## Installation and recovery

Install `openbox --no-install-recommends`, retain the vendor Xorg and input stack,
then run `deploy/minimal-kiosk/install.sh` as root from the project directory.
This stages the session without restarting it. Stop the kiosk browser, restart
the display manager, then start the browser. Confirm geometry and touch before
removing the old desktop.

`install-splash.sh` retains the old theme name and initramfs under
`/var/lib/sammoy2-minimal-kiosk`. It does not change kernel arguments or kernel.
To restore early splash, select the saved Plymouth theme and restore/rebuild the
saved initramfs using the installed kernel version. Do not copy initramfs files
between different board/kernel versions.

Before deleting KDE, `rollback.sh` restores the previous autologin and browser
launcher. After KDE removal it refuses to switch to a missing desktop; reinstall
the recorded packages first if desktop rollback is desired. SSH remains the
recovery path. Saved settings/package plans live in `/var/lib/sammoy2-minimal-kiosk`.

`purge-desktop.py --apply` removes a validated list of desktop applications only,
protecting SDDM, Openbox, the X server, network, Docker and board packages. It
requires the minimal session to be running. `prune-desktop-libraries.py` retains
vendor metapackages, graphics libraries and libraries linked by the custom
Chromium binary before validating an unused-dependency removal plan. Both are
installer tools, not jobs run during customer factory reset.

No financial data, licence, NFC/NV9 counter or shared-wallet policy is changed.
A full application reset retains this OS session and reopens installation.

## Verification

- Browser tests: local file survives HTTP connection failure and enters launch;
  launch routes fresh/commissioned installs correctly and retries backend errors.
- Actual screen: 1080x1920 rotation and ILITEK transformation retained.
- User confirmed interface, touch, branded boot after reboot and no mouse cursor.
- Chromium main process killed deliberately; systemd recovered it automatically.
- Initial memory: about 1201 MiB used. Minimal running session before package
  cleanup: approximately 850–950 MiB; measurements vary with page/cache state.
- Initial boot: 27.2 s. First minimal reboot: 30.4 s. No boot-speed improvement
  claimed from this single comparison; Docker startup is part of the measurement.

A 32 GB production image should omit development tooling and update archives.
The CL3566-A needs its own vendor OS/drivers and boot splash integration; this
Radxa kernel/initramfs must not be cloned onto it.

## Final second-post measurement, 2026-10-20

After removing 29 desktop packages and 202 validated unused dependencies, the
second reboot completed in 30.3 s. Used memory shortly after startup: 826 MiB;
root filesystem used: 7.8 GiB. All five containers healthy, Openbox and Chromium
active, no failed systemd units, no dpkg audit problems. Printing service/socket
activation (CUPS) was disabled. KDE desktop rollback now requires reinstalling
the recorded desktop packages; minimal-session recovery remains available by SSH.

## Owner navigation on a physical terminal

The kiosk launcher always uses localhost. Owner links to a different station on
this local screen render a LAN address and QR instead of navigating its browser.
On phone/computer connections the same link uses a new tab with noopener, keeping
the original station open. This applies to the site overview, equipment policy
and installation's primary Telegram link. A station-screen button on management
and login pages uses the existing unsaved-change confirmation, clears the local
session and attempts logout (bounded to three seconds), then opens same-origin
`/wash`; the existing commissioning gate handles unfinished installations.

Verified on post 2 only: kiosk QR vs LAN browser link, responsive header,
logout/token clearing, installation Telegram roles and a live login-to-wash
return without mutations to settings or money.

## Orientation after vendor HDMI toggle (2026-10-21)

Post 2 retained HDMI-1/right in display.conf, but live RandR was normal,
1920x1080. Vendor hdmi-toggle-once.service runs after SDDM with a 15-second
delay and performs a 1280x720 -> preferred-resolution switch after the minimal
session initially applies rotation. Added an ExecStartPost drop-in invoking
restore-display.py; it reapplies the saved output/rotation with a valid X
cookie and disables blanking. Vendor mode initialization is retained.

Deployed only the helper and drop-in to post 2, daemon-reloaded, applied the
helper live: verified HDMI-1 right, 1080x1920. Application/browser/IO services
were not restarted. Touch Xorg transformation remains unchanged. Loaded unit
shows the ExecStartPost for subsequent boots; reboot validation pending.
Installer and future golden-copy sanitizer install the same drop-in. The
already-exported IMG on Windows predates this fix: apply it to the new board
after first boot, without rewriting the card. New board IP/access pending.
