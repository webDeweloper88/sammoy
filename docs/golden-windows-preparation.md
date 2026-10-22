# Подготовка Windows 11 к снятию исходного образа

Согласовано: третий Cubie A7A, microSD 64 GB, тот же экран/поворот.
`G:\001_sammoy` — хранение (по словам пользователя, свободно 126 GB),
`D:` — новая карта. Источник — пост 2, `10.10.10.7`, wash/minimal kiosk.
Пост 1 остаётся рабочей средой разработки.

## Что подготовлено

`deploy/golden/windows/01-CHECK.cmd` запускает read-only preflight:
свободное место/FS G:, физические диски и фактический размер новой карты,
список WSL. Никакого подключения к постам, установки программ и raw writes.

`Read-LabrixCard.ps1` снимает выключенную исходную карту только на Windows,
с правами администратора. Все raw handles — FileAccess.Read. Проверяется
IsBoot/IsSystem, съёмный интерфейс, точный размер/3 раздела осмотренной карты,
другой физический диск назначения, NTFS/exFAT, свободное место и отсутствие
файла назначения. Незавершённая копия остаётся .partial. Полная получает SHA-256
и manifest со статусом PRIVATE_RAW_SOURCE_NOT_GOLDEN. Буква D: не используется
для выбора исходника. Доступ к рабочим постам/их данным скриптам не нужен.

Read-only осмотр поста 2: носитель 63 864 569 856 B, GPT/512 B; разделы:
16 MiB vfat с LBA32768, 300 MiB vfat с LBA65536, ext4 с LBA679936,
124055519 секторов. rootfs занято 8 495 157 248 B при осмотре. Эти величины —
предохранитель для конкретного исходника, а не универсальный лимит золотого образа.
Новая карта может быть меньше исходной, даже если обе названы 64 GB.

## Следующие контрольные точки

- [x] Осмотреть исходный носитель/разделы без изменений поста.
- [x] Подготовить Windows preflight и чтение исходной SD.
- [x] Проверить существующие isolated exporter/identity tests.
- [ ] Выполнить preflight на Windows; подтвердить Get-Disk.Size новой карты/WSL2.
- [ ] Корректно выключить пост 2, снять и хешировать исходную SD на Windows.
- [ ] Офлайн подготовить/проверить очистку отдельной копии, не оригинала.
- [ ] Согласовать новые Docker images: версия wash-engine должна включать
  site_policy fix для fog-primary, io-helper — выбранный board reader,
  UI — последний installer и minimal kiosk. Нельзя брать старый candidate19.
- [ ] Проверить уникальную системную/прикладную identity и начальный вход.
- [ ] Очистить свободные блоки, уменьшить ext4/GPT и получить новый manifest.
- [ ] Записать на третью карту, проверить /install и post3/shared wallet.

Первый запуск копии до удаления старых Docker auto-restart containers и
индивидуальных ключей запрещён в рабочей сети: это был бы второй экземпляр
поста 2. Офлайн-подготовка не реализована в этом Windows-пакете; она требует
полученного согласованного образа и проверки Linux-среды. Нельзя выдавать
пакет подготовки или source export за готовый загрузочный golden image.

Ограничение WSL `--mount` для SD/USB описано Microsoft:
https://learn.microsoft.com/windows/wsl/wsl2-mount-disk.
На Windows эти PowerShell scripts ещё не выполнялись; текущие Linux-проверки
не заменяют их фактический запуск на целевом ПК.


## WSL preflight and working copy

User confirmed Windows 11, Ubuntu WSL2/x86_64; physical free space C:
93,164,208,128 B and G:62,487,040,000 B after capture. Linux virtual ext4 free
954 GiB is not physical SSD capacity. sfdisk/sgdisk/e2fsck/resize2fs/python3
present; zerofree/zstd not yet present (not needed for the copying step).
Original captured and SHA-256 printed successfully:
G:\001_sammoy\LABRIX-SOURCE-POST2-20261021-121320.img.
Source card returned, both posts running. Original file must not be modified.

Separate LABRIX-Working-Copy.zip checks the Ubuntu registry BasePath's drive
and physical free space, converts paths through wslpath, runs an independent
sparse copy in Linux /var/lib/labrix-golden-build, validates source sidecar/GPT
and both hashes, refuses existing workdir/target and does not mount or clean.
8 isolated golden/copy tests pass. Target Windows/WSL execution still pending.


Windows execution found legacy WSL command-line forwarding stripped Windows
backslashes before wslpath; Python copy never started. Version 2 uses explicit
/mnt/<drive> conversion (mount /mnt/g already confirmed), --exec to bypass shell
parsing, and read-only existence/readability probes before invoking Python.
Original .img and workdir were not changed by the failed attempt.
Eight Linux golden/copy tests pass; corrected Windows execution pending.


Working copy verified on user's WSL: logical 63,864,569,856 B; allocated
16,955,355,136 B. SHA-256 e911ea253c0441b0456fe8fadfba921b93ec6e1f4aa16eea65b720035b87b59b.
Original unchanged, no sanitizing/shrinking yet. Separate third-step inspector
attaches only WORK image partitions using read-only loops and ro/noload for
ext4, noexec/nodev/nosuid; outputs sanitized inventory, then unmounts/detaches.
Actual isolated 64-MiB ext4 test on host passed: write denied (EROFS), file
mtime unchanged and loop detached. User WSL inspection still pending.

2026-10-21: user WSL read-only inspection succeeded, all loops detached.
Debian 11, portrait HDMI-1/right, config.txt/logo.bmp retained. Inventory
confirmed private application DB/env, machine-id, SSH host keys and NM profiles.
Container images primarily reside in /var/lib/containerd (2.31 GB); deleting
only /var/lib/docker would leave old runtime state. No sanitation performed.
Installer-key package generates an Ed25519 key interactively on Windows and
prints only its public half; existing keys are never overwritten. Public key
is needed before removing cloned OS credentials. Private key must never enter
the image or this repository. Actual Windows key-generation run pending.

Installer public key received and fingerprint verified:
SHA256:O8FC+oD09+6oBi5YAjc1WFnqouqfEIZQgAxTr+HHYX8.
Private key stays on Windows. Source OS model is `sun60iw2` (vendor DT), not
the retail board name; first-card expansion recognizes this value. Original
GPT partitions 2 AND 3 have LegacyBIOSBootable, which shrinking must preserve.

User requested a ready-to-flash image rather than separate manual cleanup
stages. Unified 06-BUILD-IMAGE runs cleanup, ext4 shrink to 16 GiB, GPT backup
relocation, full free-block zeroing, optional hole punching, verified export to
G:\001_sammoy\LABRIX-CUBIE-A7A-GOLDEN-20261021.img. Only WORK is edited.
07-WRITE-NEW-CARD verifies export SHA before disk selection, refuses boot/system
disks and the source's full-size Linux partition signature, requires removable
64-GB target and exact typed WRITE NEW N after displaying the device, then
clears/writes/verifies every written byte. Windows writer execution is pending.

Validation completed here: 12 isolated tests; real mounted ext4 sanitizing with
the full app export; real GPT/ext4 shrink and free-block scrub (old private
sentinel contents absent), original UUID/legacy flags/boot prefix retained;
larger-card GPT growth with the exact sfdisk command and online ext4 growth;
all five ARM64 image identities loaded into an EMPTY isolated Docker 29.8;
fresh PostgreSQL+engine startup with uncommissioned state, no site identity,
customer access denied, initial Owner/Admin logins valid and password changes
required. Test containers had no host ports or hardware and were removed.

Factory OS drops copied home directories/password hashes/SSH host keys/network
profiles and Docker+containerd state. First boot generates machine/host/app
identities, allows SSH only with installer key, gives admin-owned mode-0600
~/labrix-first-login.txt for unique sudo/Owner/Admin passwords. No old licensed
identity, funds/card DB or Telegram volume is shipped. Factory-only starts
/install; hardware profile selected during commissioning. No scheduled backup
timer enabled. Docker loader uses local verified archive then deletes it.
Auto-growth is best effort, with retry marker; setup remains usable on 16-GiB
root if live growth needs another boot. Physical third-board boot is pending.

Windows run reached the free-block scrub after successful sanitation and GPT/
ext4 reduction, then threw ENOSPC after 11.34 GiB of temporary zero-file data.
The previous f_bfree<=4-MiB check incorrectly assumed allocator exhaustion is
equivalent to that raw counter. The temporary file remains, loops were handled
by finally, and manifest is FINALIZING_WORKING_COPY. Do NOT rerun sanitation.

Replaced allocation-to-exhaustion with offline zerofree and a second dry scan
requiring zero nonzero free blocks. Debian zerofree 1.1.1-1 amd64 package SHA
matched the official bookworm Packages index; tiny bundled binary SHA pinned,
copied to the private Linux build directory before execution. Include upstream
source, Debian build source/copyright and GPL2 text. No installation into the
Radxa image; no network required on Windows. Native ARM build of same version
tested locally. Fifteen unit tests pass, including refusal to scrub a mounted
filesystem or accept nonzero verification; no statvfs/file-filling dependency.
Real 4-KiB ext4 full-disk interruption reproduced, stale temporary file removed,
deleted private sentinel blocks zeroed, allocated active data retained, full
export hash and no-overwrite checked.

Small Resume package verifies the EXACT interrupted state, original/reduced
GPT GUIDs, partition UUIDs/types/names/attributes, original bootloader+VFAT
regions read-only and original filesystem UUID. Only then removes our own
temporary file, scrubs/checks unmounted WORK and exports the ready .img. It
does not repeat cleanup/shrinking and never writes an SD. User explicitly chose
to save IMG first, then flash separately with balenaEtcher; do not use 07 writer.
Windows execution of the resume helper and physical new-board boot pending.
