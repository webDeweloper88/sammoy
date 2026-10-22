import crypt
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from identity import initialize as app_identity
from os_identity import initialize as os_identity, public_key

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('clean_copy', HERE / 'windows/Clean-WorkingCopy.py')
clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean)
KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBiNvIv9ZRcpmAjSuegkQIj98uQXqR1VTOXT1JJd6gwx LABRIX-installer\n'


def fixture(root, release):
    tree = clean.Tree(root)
    uid, gid = os.getuid(), os.getgid()
    # The production guard expects normal Debian interactive account IDs.
    if uid < 1000:
        uid = 1000
    tree.write('etc/passwd', f'root:x:0:0:root:/root:/bin/bash\nadmin:x:{uid}:{gid}:Admin:/home/admin:/bin/bash\nkiosk:x:{uid}:{gid}:Kiosk:/home/kiosk:/bin/bash\n')
    tree.write('etc/shadow', 'root:old-root-hash:20000:0:99999:7:::\nadmin:old-admin-hash:20000:0:99999:7:::\nkiosk:old-kiosk-hash:20000:0:99999:7:::\n', 0o600)
    tree.write('etc/shadow-', 'old-private-password')
    tree.write('etc/gshadow', 'root:old-group-hash::\n')
    tree.write('etc/os-release', 'VERSION_ID="11"\n')
    tree.write('etc/machine-id', 'old-machine-id\n')
    tree.write('var/lib/dbus/machine-id', 'old-machine-id\n')
    tree.write('etc/sammoy2/display.conf', 'KIOSK_OUTPUT=HDMI-1\nKIOSK_ROTATION=right\n')
    for name in ('opt/sammoy/sammoy2/.env', 'opt/sammoy/sammoy2/data/money',
                 'opt/containerd/old-state', 'var/lib/docker/container-env',
                 'var/lib/containerd/old-volumes', 'home/admin/.ssh/id_ed25519',
                 'home/kiosk/.config/browser-cookies', 'root/.bash_history',
                 'etc/NetworkManager/system-connections/old-static',
                 'etc/ssh/ssh_host_ed25519_key', 'var/backups/database.sql',
                 'var/lib/sammoy2-admin/system-job.json', 'var/log/private-log'):
        tree.write(name, 'SOURCE_PRIVATE')
    tree.write('etc/systemd/system/sammoy2-post.service', 'old-runtime\n')
    tree.directory('etc/systemd/system/timers.target.wants')
    tree.path('etc/systemd/system/timers.target.wants/sammoy2-backup.timer').symlink_to('/etc/systemd/system/sammoy2-backup.timer')
    tree.write('boot/kernel-proof', 'keep kernel and initrd')
    release.mkdir()
    (release / 'installer.pub').write_text(KEY)
    for name in ('images.tar.gz', 'images.json', 'release.json'):
        (release / name).write_text('TEST_RELEASE')
    project = HERE.parents[1]
    members = {'GOLDEN_TEMPLATE.json': b'{"state":"uncommissioned"}',
               'apps/kiosk-ui/public/assets/theme2/brand/labrix_mark_L.png': b'PNG_TEST'}
    paths = ['deploy/' + name for name in ('sammoy2-post.service', 'sammoy2-admin-system.service',
             'sammoy2-admin-network.service', 'sammoy2-pn532-i2c.service', 'sammoy2-log-retention.service',
             'sammoy2-log-retention.timer', 'sammoy2-journald.conf')]
    paths += ['deploy/golden/' + name for name in ('sammoy2-factory-grow.service', 'sammoy2-factory-identity.service', 'sammoy2-factory-images.service', 'sammoy2-factory-app.service')]
    paths += ['deploy/minimal-kiosk/' + name for name in ('labrix-kiosk.desktop', 'openbox.xml', 'boot.html', 'hdmi-orientation.conf')]
    for name in paths:
        members[name] = (project / name).read_bytes()
    with tarfile.open(release / 'application.tar.gz', 'w:gz') as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return tree


class SanitationTests(unittest.TestCase):
    def test_copy_cleaning_removes_source_state_preserves_boot_and_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, release = Path(tmp) / 'root', Path(tmp) / 'release'
            root.mkdir()
            fixture(root, release)
            result = clean.sanitize_root(root, release)
            self.assertTrue(result['display_preserved'])
            self.assertFalse((root / 'opt/sammoy/sammoy2/.env').exists())
            self.assertFalse((root / 'opt/sammoy/sammoy2/data').exists())
            for name in ('var/lib/docker', 'var/lib/containerd', 'home/admin', 'home/kiosk', 'root'):
                self.assertNotIn('SOURCE_PRIVATE', ''.join(p.read_text() for p in (root / name).rglob('*') if p.is_file()))
            self.assertFalse((root / 'etc/shadow-').exists())
            self.assertNotIn('old-', (root / 'etc/shadow').read_text())
            self.assertEqual((root / 'boot/kernel-proof').read_text(), 'keep kernel and initrd')
            self.assertEqual((root / 'etc/machine-id').read_text(), '')
            self.assertEqual(os.readlink(root / 'var/lib/dbus/machine-id'), '/etc/machine-id')
            self.assertFalse((root / 'etc/systemd/system/timers.target.wants/sammoy2-backup.timer').is_symlink())
            self.assertEqual((root / 'home/admin').stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / 'tmp').stat().st_mode & 0o7777, 0o1777)

    def test_unsafe_archive_members_and_parent_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for i, name in enumerate(('../outside', '/etc/shadow', 'ok/link')):
                archive = base / f'{i}.tar.gz'
                with tarfile.open(archive, 'w:gz') as tar:
                    item = tarfile.TarInfo(name)
                    item.type = tarfile.SYMTYPE if i == 2 else tarfile.REGTYPE
                    item.linkname = '/etc/shadow'
                    tar.addfile(item)
                with self.assertRaises(RuntimeError):
                    clean.extract_application(archive, base / f'out{i}')
            root = base / 'root'; root.mkdir()
            (root / 'escape').symlink_to(base, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                clean.Tree(root).write('escape/danger', 'must not happen')
            self.assertFalse((base / 'danger').exists())

    def test_first_boot_creates_unique_access_and_retry_does_not_rotate(self):
        with tempfile.TemporaryDirectory() as tmp:
            clones = []
            for i in ('a', 'b'):
                root, release = Path(tmp) / i, Path(tmp) / (i + '-release')
                root.mkdir(); fixture(root, release)
                clean.sanitize_root(root, release)
                app_identity(root / 'opt/sammoy/sammoy2')
                os_identity(root)
                before = (root / 'etc/shadow').read_bytes()
                os_identity(root)
                self.assertEqual(before, (root / 'etc/shadow').read_bytes())
                self.assertEqual((root / 'home/admin/.ssh/authorized_keys').read_text(), KEY)
                self.assertEqual((root / 'home/admin/labrix-first-login.txt').stat().st_mode & 0o777, 0o600)
                secret = json.loads((root / 'var/lib/sammoy2/os-first-access.json').read_text())
                hashed = next(s.split(':')[1] for s in (root / 'etc/shadow').read_text().splitlines() if s.startswith('admin:'))
                self.assertEqual(crypt.crypt(secret['admin_password'], hashed), hashed)
                clones.append(secret['admin_password'])
            self.assertNotEqual(*clones)

    def test_public_key_format_rejects_truncation_or_multiple_lines(self):
        self.assertEqual(public_key(KEY), KEY)
        for value in ('ssh-ed25519 YWJj', KEY + KEY, 'ssh-rsa AAAA installer'):
            with self.assertRaises(ValueError):
                public_key(value)


if __name__ == '__main__':
    unittest.main()
