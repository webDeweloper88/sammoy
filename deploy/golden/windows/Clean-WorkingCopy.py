#!/usr/bin/env python3
"""Sanitize only the inspected private WSL WORK copy. Never writes an SD/source."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile

WORK = Path('/var/lib/labrix-golden-build')
IMAGE = WORK / 'LABRIX-WORK.img'
ROOT_OFFSET = 679936 * 512
ROOT_LENGTH = 124055519 * 512
MOUNT = Path('/mnt/labrix-clean-root')
EXPECTED_SOURCE = 'e911ea253c0441b0456fe8fadfba921b93ec6e1f4aa16eea65b720035b87b59b'


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def boot_prefix_sha(image):
    h = hashlib.sha256()
    remaining = ROOT_OFFSET
    with image.open('rb') as stream:
        while remaining:
            block = stream.read(min(8 * 1024**2, remaining))
            if not block:
                raise RuntimeError('Truncated boot prefix')
            h.update(block)
            remaining -= len(block)
    return h.hexdigest()


class Tree:
    """Whitelist operations confined to a mounted root, without following links."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        if self.root == Path('/'):
            raise RuntimeError('Refusing live filesystem')

    def path(self, relative):
        rel = PurePosixPath(relative)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise RuntimeError('Unsafe relative path')
        p = self.root.joinpath(*rel.parts)
        # Resolve the parent only: unlinking a final symlink is safe.
        if not p.parent.resolve().is_relative_to(self.root):
            raise RuntimeError('Parent escapes offline root: ' + relative)
        current = self.root
        for part in rel.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise RuntimeError('Symlink parent in offline path: ' + relative)
        return p

    def remove(self, relative):
        p = self.path(relative)
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        elif os.path.lexists(p):
            raise RuntimeError('Unexpected special path: ' + relative)

    def directory(self, relative, mode=None, owner=None):
        if relative == '.':
            return self.root
        p = self.path(relative)
        if p.is_symlink():
            raise RuntimeError('Directory symlink: ' + relative)
        p.mkdir(parents=True, mode=mode if mode is not None else 0o755, exist_ok=True)
        if mode is not None:
            p.chmod(mode)
        if owner is not None:
            os.chown(p, *owner)
        return p

    def write(self, relative, value, mode=0o644, owner=None):
        p = self.path(relative)
        self.directory(str(PurePosixPath(relative).parent))
        if p.is_symlink():
            raise RuntimeError('File symlink: ' + relative)
        p.write_text(value)
        p.chmod(mode)
        if owner is not None:
            os.chown(p, *owner)


def account_ids(tree):
    users = {}
    for line in tree.path('etc/passwd').read_text().splitlines():
        f = line.split(':')
        if 1000 <= int(f[2]) < 65534:
            if f[0] not in ('admin', 'kiosk') or f[5] != '/home/' + f[0]:
                raise RuntimeError('Unrecognized interactive account; review needed')
            users[f[0]] = (int(f[2]), int(f[3]))
    if set(users) != {'admin', 'kiosk'}:
        raise RuntimeError('Source accounts differ from inspected board')
    return users


def extract_application(archive, destination):
    """Extract only plain files/directories; reject links, traversal and devices."""
    tree = Tree(destination)
    destination.mkdir(mode=0o755)
    seen = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for entry in tar:
            rel = PurePosixPath(entry.name)
            if rel.is_absolute() or '..' in rel.parts or not rel.parts or entry.name in seen:
                raise RuntimeError('Unsafe/duplicate application archive member')
            seen.add(entry.name)
            if entry.isdir():
                tree.directory(str(rel), 0o755)
            elif entry.isfile() and entry.size <= 128 * 1024**2:
                p = tree.path(str(rel))
                tree.directory(str(rel.parent))
                with tar.extractfile(entry) as src, p.open('xb') as dst:
                    shutil.copyfileobj(src, dst, 1024**2)
                p.chmod(0o755 if entry.mode & 0o111 else 0o644)
            else:
                raise RuntimeError('Only regular application files/directories allowed')
    if not (destination / 'GOLDEN_TEMPLATE.json').is_file():
        raise RuntimeError('Export marker missing')
    if (destination / '.env').exists() or (destination / 'data').exists():
        raise RuntimeError('Private application data in release')


def install_unit(tree, name, contents, target='multi-user.target'):
    tree.write('etc/systemd/system/' + name, contents)
    wants = 'etc/systemd/system/' + target + '.wants'
    tree.directory(wants)
    p = tree.path(wants + '/' + name)
    if os.path.lexists(p):
        p.unlink()
    p.symlink_to('/etc/systemd/system/' + name)


def sanitize_root(root, release):
    tree = Tree(root)
    release = Path(release)
    os_release = tree.path('etc/os-release')
    # Debian os-release commonly symlinks into /usr/lib inside the image.
    if os_release.is_symlink():
        os_release = tree.path('usr/lib/os-release')
    if 'VERSION_ID="11"' not in os_release.read_text():
        raise RuntimeError('Expected inspected Debian 11 OS')
    users = account_ids(tree)
    docker_config = tree.path('etc/docker/daemon.json')
    if docker_config.exists():
        docker_data = json.loads(docker_config.read_text())
        if docker_data.get('data-root', '/var/lib/docker') != '/var/lib/docker':
            raise RuntimeError('Custom Docker data-root needs separate sanitation review')
    display = tree.path('etc/sammoy2/display.conf').read_text()
    if display != 'KIOSK_OUTPUT=HDMI-1\nKIOSK_ROTATION=right\n':
        raise RuntimeError('Unexpected display configuration')
    # Verify before deletion: source units are hardware-specific but must not
    # contain an unexpected custom autostart or privileged maintenance program.
    units = tree.path('etc/systemd/system')
    known = {'sammoy2-admin-network.service', 'sammoy2-admin-system.service',
             'sammoy2-backup.service', 'sammoy2-backup.timer', 'sammoy2-kiosk.service',
             'sammoy2-kiosk.service.d', 'sammoy2-log-retention.service',
             'sammoy2-log-retention.timer', 'sammoy2-pn532-i2c.service', 'sammoy2-post.service'}
    if any(p.name.startswith(('sammoy2', 'labrix')) and p.name not in known for p in units.iterdir()):
        raise RuntimeError('Unrecognized custom LABRIX unit')
    for p in tree.path('home').iterdir():
        if p.name not in users:
            raise RuntimeError('Unexpected home directory; review needed')
    # All these paths belong to the COPY. No commands from that OS are executed.
    paths = ('opt/sammoy', 'opt/containerd', 'var/lib/docker', 'var/lib/containerd',
             'var/lib/sammoy2', 'var/lib/sammoy2-admin', 'var/lib/sammoy2-minimal-kiosk',
             'var/lib/NetworkManager', 'var/lib/dhcp', 'var/lib/bluetooth',
             'var/lib/systemd/random-seed', 'var/lib/systemd/rfkill',
             'var/lib/AccountsService/users', 'var/lib/AccountsService/icons',
             'var/backups', 'var/log', 'var/cache', 'var/tmp', 'tmp',
             'var/spool/cron', 'var/lib/apt/lists',
             'etc/NetworkManager/system-connections', 'etc/sudoers.d',
             'home/admin', 'home/kiosk', 'root', 'etc/sammoy2', 'opt/labrix-factory')
    for relative in paths:
        tree.remove(relative)
    for name in ('admin', 'kiosk'):
        tree.directory('home/' + name, 0o700, users[name])
        tree.write('home/' + name + '/.profile', 'if [ -n "$BASH_VERSION" ] && [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n', owner=users[name])
        tree.write('home/' + name + '/.bashrc', 'export PS1="\\u@\\h:\\w\\$ "\n', owner=users[name])
    tree.directory('root', 0o700)
    for relative in ('var/lib/docker', 'var/lib/containerd', 'var/lib/NetworkManager',
                     'var/log', 'var/cache', 'var/backups', 'var/lib/apt/lists/partial'):
        tree.directory(relative)
    tree.directory('tmp', 0o1777)
    tree.directory('var/tmp', 0o1777)
    tree.directory('var/lib/sammoy2', 0o700)
    tree.directory('var/lib/sammoy2-admin', 0o700)
    tree.directory('etc/NetworkManager/system-connections', 0o700)
    tree.write('etc/NetworkManager/system-connections/labrix-ethernet.nmconnection',
               '[connection]\nid=LABRIX Ethernet\ntype=ethernet\nautoconnect=true\n'
               'autoconnect-priority=100\n\n[ethernet]\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n', 0o600)
    tree.write('etc/sammoy2/display.conf', display)
    tree.write('etc/sammoy2/installer.pub', (release / 'installer.pub').read_text())
    tree.write('etc/hostname', 'labrix-factory\n')
    tree.write('etc/hosts', '127.0.0.1\tlocalhost\n127.0.1.1\tlabrix-factory\n::1\tlocalhost ip6-localhost ip6-loopback\n')
    tree.remove('etc/machine-id')
    tree.write('etc/machine-id', '')
    tree.remove('var/lib/dbus/machine-id')
    tree.path('var/lib/dbus/machine-id').symlink_to('/etc/machine-id')
    for p in tree.path('etc/ssh').glob('ssh_host_*'):
        tree.remove(str(p.relative_to(root)))
    tree.remove('etc/ssh/ssh_known_hosts')
    tree.remove('etc/ssl/private/ssl-cert-snakeoil.key')
    tree.remove('etc/ssl/certs/ssl-cert-snakeoil.pem')
    tree.remove('etc/ssh/sshd_config.d')
    tree.directory('etc/ssh/sshd_config.d')
    tree.write('etc/ssh/sshd_config',
               'Port 22\nPermitRootLogin no\nPubkeyAuthentication yes\n'
               'AuthorizedKeysFile .ssh/authorized_keys\nPasswordAuthentication no\n'
               'ChallengeResponseAuthentication no\nUsePAM yes\nX11Forwarding no\n'
               'PrintMotd no\nAcceptEnv LANG LC_*\nSubsystem sftp /usr/lib/openssh/sftp-server\n')
    tree.directory('etc/sudoers.d', 0o755)
    tree.write('etc/sudoers.d/labrix-installer', 'admin ALL=(ALL:ALL) ALL\n', 0o440)
    # Remove source passwords also from shadow/gshadow backup files.
    shadow = tree.path('etc/shadow')
    rows = []
    for row in shadow.read_text().splitlines():
        f = row.split(':')
        f[1] = '!' if f[0] == 'root' else '*'
        rows.append(':'.join(f))
    shadow.write_text('\n'.join(rows) + '\n')
    shadow.chmod(0o640)
    for name in ('shadow-', 'passwd-', 'gshadow-', 'group-'):
        tree.remove('etc/' + name)
    gshadow = tree.path('etc/gshadow')
    if gshadow.exists():
        rows = []
        for row in gshadow.read_text().splitlines():
            f = row.split(':'); f[1] = '!'; rows.append(':'.join(f))
        gshadow.write_text('\n'.join(rows) + '\n')
        gshadow.chmod(0o640)
    for p in tree.path('etc').glob('wpa_supplicant/*.conf'):
        tree.remove(str(p.relative_to(root)))
    # An inherited serial-console autologin must not bypass the new identity.
    for p in units.glob('*getty*.service.d'):
        tree.remove(str(p.relative_to(root)))
    tree.directory('opt/sammoy')
    app = tree.path('opt/sammoy/sammoy2')
    extract_application(release / 'application.tar.gz', app)
    tree.write('opt/sammoy/sammoy2/.hardware-profile', 'factory-only\n')
    tree.directory('opt/labrix-factory', 0o700)
    for name in ('images.tar.gz', 'images.json', 'release.json'):
        shutil.copyfile(release / name, tree.path('opt/labrix-factory/' + name))
        tree.path('opt/labrix-factory/' + name).chmod(0o600)
    # Replace source LABRIX units/drop-ins with the exact reviewed release.
    for p in list(units.iterdir()):
        if p.name.startswith(('sammoy2', 'labrix')):
            tree.remove(str(p.relative_to(root)))
    for target in units.glob('*.wants'):
        if target.is_symlink() or not target.is_dir():
            continue
        for link in target.iterdir():
            if link.name.startswith(('sammoy2', 'labrix')):
                tree.remove(str(link.relative_to(root)))
    for name in ('sammoy2-post.service', 'sammoy2-admin-system.service',
                 'sammoy2-admin-network.service', 'sammoy2-pn532-i2c.service'):
        install_unit(tree, name, (app / 'deploy' / name).read_text())
    for name in ('sammoy2-factory-grow.service', 'sammoy2-factory-identity.service', 'sammoy2-factory-images.service', 'sammoy2-factory-app.service'):
        install_unit(tree, name, (app / 'deploy/golden' / name).read_text())
    for name in ('sammoy2-log-retention.service', 'sammoy2-log-retention.timer'):
        text = (app / 'deploy' / name).read_text()
        if name.endswith('.timer'):
            install_unit(tree, name, text, 'timers.target')
        else:
            tree.write('etc/systemd/system/' + name, text)
    tree.write('etc/systemd/journald.conf.d/sammoy2.conf', (app / 'deploy/sammoy2-journald.conf').read_text())
    identity_order = '[Unit]\nRequires=sammoy2-factory-identity.service\nAfter=sammoy2-factory-identity.service\n'
    for name in ('docker.service', 'ssh.service', 'ssh.socket', 'display-manager.service', 'sddm.service'):
        tree.write('etc/systemd/system/' + name + '.d/sammoy2-factory.conf', identity_order)
    tree.write('etc/systemd/system/sammoy2-post.service.d/factory-images.conf',
               '[Unit]\nRequires=sammoy2-factory-images.service\nAfter=sammoy2-factory-images.service\n')
    kiosk_unit = ('[Unit]\nDescription=LABRIX touchscreen kiosk\nAfter=display-manager.service docker.service\n'
                  'Wants=display-manager.service docker.service\nStartLimitIntervalSec=0\n\n'
                  '[Service]\nType=simple\nUser=kiosk\nGroup=kiosk\nEnvironment=DISPLAY=:0\n'
                  'Environment=XAUTHORITY=/home/kiosk/.Xauthority\nEnvironment=XCURSOR_THEME=SAMMOY-Invisible\n'
                  'ExecStart=/opt/sammoy/sammoy2/deploy/minimal-kiosk/launcher.sh\n'
                  'Restart=always\nRestartSec=3\nKillMode=control-group\nTimeoutStopSec=15\n\n'
                  '[Install]\nWantedBy=graphical.target\n')
    install_unit(tree, 'sammoy2-kiosk.service', kiosk_unit, 'graphical.target')
    tree.write('etc/sddm.conf.d/90-labrix-minimal.conf', '[Autologin]\nUser=kiosk\nSession=labrix-kiosk.desktop\nRelogin=true\n')
    tree.write('etc/systemd/system/hdmi-toggle-once.service.d/90-labrix-orientation.conf',
               (app / 'deploy/minimal-kiosk/hdmi-orientation.conf').read_text())
    tree.write('usr/share/xsessions/labrix-kiosk.desktop', (app / 'deploy/minimal-kiosk/labrix-kiosk.desktop').read_text())
    tree.write('etc/sammoy2/openbox.xml', (app / 'deploy/minimal-kiosk/openbox.xml').read_text())
    tree.write('usr/local/share/labrix-kiosk/boot.html', (app / 'deploy/minimal-kiosk/boot.html').read_text())
    shutil.copyfile(app / 'apps/kiosk-ui/public/assets/theme2/brand/labrix_mark_L.png',
                    tree.path('usr/local/share/labrix-kiosk/labrix.png'))
    tree.write('var/lib/sammoy2/factory-pending', '1\n', 0o600)
    tree.write('var/lib/sammoy2/grow-pending', '1\n', 0o600)
    # No regular user has a source password, key, home or browser session now.
    if (app / '.env').exists() or (app / 'data').exists():
        raise RuntimeError('Application identity survived cleaning')
    if list(tree.path('etc/ssh').glob('ssh_host_*')):
        raise RuntimeError('Source SSH host key survived cleaning')
    return {'sanitized_paths': list(paths), 'identity': 'GENERATE_ON_FIRST_BOOT',
            'network': 'ETHERNET_DHCP_NO_SOURCE_PROFILES', 'hardware_profile': 'factory-only',
            'application_data_present': False, 'source_ssh_host_keys_present': False,
            'backup_timer_enabled': False, 'boot_partitions_modified': False,
            'display_preserved': True}


@contextmanager
def writable_root():
    if MOUNT.exists() or MOUNT.is_symlink():
        raise RuntimeError('Offline mountpoint already exists')
    loop = output('losetup', '--find', '--show', '--offset', str(ROOT_OFFSET),
                  '--sizelimit', str(ROOT_LENGTH), str(IMAGE))
    mounted = False
    try:
        if output('blockdev', '--getro', loop) != '0':
            raise RuntimeError('Working loop must be writable')
        rc = subprocess.run(['e2fsck', '-f', '-p', loop]).returncode
        if rc not in (0, 1):
            raise RuntimeError('Working root filesystem needs manual fsck review')
        MOUNT.mkdir(mode=0o700)
        subprocess.run(['mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid,noexec', loop, str(MOUNT)], check=True)
        mounted = True
        yield MOUNT
    finally:
        if mounted:
            subprocess.run(['umount', str(MOUNT)], check=True)
        subprocess.run(['losetup', '--detach', loop], check=True)
        if MOUNT.exists():
            MOUNT.rmdir()


def clean(release):
    release = Path(release).resolve()
    if os.geteuid() != 0 or release == Path('/'):
        raise RuntimeError('WSL root and extracted release directory required')
    manifest = json.loads((WORK / 'working-copy.json').read_text())
    if manifest.get('state') != 'VERIFIED_PRIVATE_WORKING_COPY_NOT_GOLDEN' or manifest.get('source_sha256') != EXPECTED_SOURCE:
        raise RuntimeError('Unexpected working-copy state; refusing automatic retry')
    if IMAGE.is_symlink() or IMAGE.stat().st_nlink != 1 or IMAGE.stat().st_size != 63864569856:
        raise RuntimeError('Working image identity/size mismatch')
    if not json.loads((WORK / 'inspection.json').read_text()).get('working_image_unchanged'):
        raise RuntimeError('Successful read-only inspection required')
    source = Path(manifest['source'])
    if source.resolve() == IMAGE.resolve() or os.path.samefile(source, IMAGE):
        raise RuntimeError('Source and working image must differ')
    original = source.stat()
    if original.st_size != 63864569856:
        raise RuntimeError('Original size differs')
    if output('losetup', '-j', str(IMAGE)):
        raise RuntimeError('Working image already attached; detach safely first')
    layout = json.loads(output('sfdisk', '--json', str(IMAGE)))['partitiontable']
    if layout.get('label') != 'gpt' or layout.get('sectorsize') != 512 or [(p['start'], p['size']) for p in layout['partitions']] != [(32768, 32768), (65536, 614400), (679936, 124055519)]:
        raise RuntimeError('Inspected partition layout changed')
    release_manifest = json.loads((release / 'release.json').read_text())
    if release_manifest.get('state') != 'CLEAN_ARM64_APPLICATION_RELEASE' or set(release_manifest['files']) != {'application.tar.gz', 'images.tar.gz', 'images.json', 'installer.pub'}:
        raise RuntimeError('Unexpected release manifest')
    for name, expected in release_manifest['files'].items():
        p = release / name
        if p.is_symlink() or not p.is_file() or sha(p) != expected:
            raise RuntimeError('Release hash mismatch: ' + name)
    # Public key is structurally validated by the same code used on first boot.
    # No image/OS code is executed here; only this trusted release helper runs.
    key = (release / 'installer.pub').read_text()
    if key != 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBiNvIv9ZRcpmAjSuegkQIj98uQXqR1VTOXT1JJd6gwx LABRIX-installer\n':
        raise RuntimeError('Installer public key differs from supplied key')
    print('Release verified. Cleaning only LABRIX-WORK.img; original and SD cards are not opened for writing.', flush=True)
    boot_hash = boot_prefix_sha(IMAGE)
    manifest['state'] = 'SANITIZING_PRIVATE_WORKING_COPY'
    (WORK / 'working-copy.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with writable_root() as root:
        report = sanitize_root(root, release)
    if boot_prefix_sha(IMAGE) != boot_hash:
        raise RuntimeError('Boot-prefix hash changed unexpectedly; do not boot this copy')
    report['boot_prefix_sha256'] = boot_hash
    report['boot_prefix_unchanged'] = True
    after = source.stat()
    if (after.st_size, after.st_mtime_ns) != (original.st_size, original.st_mtime_ns):
        raise RuntimeError('Original changed externally; stop and inspect')
    manifest.update(state='SANITIZED_NOT_SHRUNK_NOT_GOLDEN', sanitized=True, shrunk=False,
                    sanitation_report=report, source_unchanged=True,
                    release_sha256=sha(release / 'release.json'))
    (WORK / 'working-copy.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'state': manifest['state'], **report}, indent=2), flush=True)
    print('COPY CLEANED. All loops detached. Free-block scrubbing, shrinking and boot tests are still required.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    clean(parser.parse_args().release)
