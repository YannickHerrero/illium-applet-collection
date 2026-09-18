import importlib.util
from pathlib import Path
import struct
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('winagotchi_install', ROOT / 'install.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.config = self.root / 'config'; self.config.mkdir()
        self.bar = self.config / 'bar.toml'
        self.original = b'\xef\xbb\xbf# Preserve me\r\nleft = ["workspaces"] # ] keep\r\ncenter = ["clock"]\r\nright = ["wifi", "claude-usage"]\r\nclock_format = "%A %d %b"\r\n'
        self.bar.write_bytes(self.original)
        image = bytearray(256); image[:2] = b'MZ'
        struct.pack_into('<I', image, 0x3c, 128); image[128:134] = b'PE\0\0\x64\x86'
        self.binary = self.root / 'winagotchi.exe'; self.binary.write_bytes(image)
        self.backups = self.root / 'backups'

    def run_install(self):
        return install.install(self.config, self.binary, r'C:\Users\Test User\.config\winarchy', self.backups)

    def test_preserves_bar_and_installs_complete_silent_pack(self):
        result = self.run_install()
        data = tomllib.loads(self.bar.read_text(encoding='utf-8-sig'))
        self.assertEqual(data['right'], ['wifi', 'claude-usage'])
        self.assertEqual(data['left'], ['winagotchi', 'workspaces']); self.assertEqual(data['center'], ['clock'])
        self.assertIn(b'# ] keep\r\n', self.bar.read_bytes())
        self.assertIn(b'clock_format = "%A %d %b"\r\n', self.bar.read_bytes())
        self.assertTrue(self.bar.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual((Path(result['backup']) / 'bar.toml').read_bytes(), self.original)
        app = Path(result['applet']); manifest = tomllib.loads((app / 'applet.toml').read_text())
        self.assertEqual(manifest['command'], [r'C:\Users\Test User\.config\winarchy\applets\winagotchi\winagotchi.exe'])
        self.assertEqual((app / 'winagotchi.exe').read_bytes(), self.binary.read_bytes())
        self.assertEqual(len(list((app / 'assets/sprites').glob('*.png'))), 83)
        for icon in app.glob('*.png'):
            self.assertEqual(icon.read_bytes(), (app / 'assets/sprites' / icon.name).read_bytes())
        self.assertTrue((app / 'sprites.slint').is_file())
        self.assertFalse((app / 'provider').exists())
        self.assertFalse((app / 'state.json').exists())
        self.assertFalse(any(p.suffix in ('.wav', '.mp3', '.ogg') for p in app.rglob('*')))

    def test_existing_installation_is_never_overwritten(self):
        self.run_install(); snapshot = self.bar.read_bytes()
        with self.assertRaises(ValueError): self.run_install()
        self.assertEqual(self.bar.read_bytes(), snapshot)

    def test_old_installation_requires_explicit_migration(self):
        (self.config / 'applets/omagotchi').mkdir(parents=True)
        with self.assertRaises(ValueError): self.run_install()
        self.assertEqual(self.bar.read_bytes(), self.original)
        self.assertFalse(self.backups.exists())

    def test_multiline_duplicate_or_bad_arrays_are_rejected(self):
        for raw in [b'left = [\n"workspaces"\n]\n', b'left = ["winagotchi"]\nright = []\n',
                    b'left=[]\nright=["omagotchi"]', b'left = 1\nright = []\n',
                    b'left = [3]\n', b'right = []\n']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): install.plan_bar(raw)

    def test_empty_unicode_and_quoted_brackets(self):
        for raw in [b'left=[]', 'left = ["日本語", "a]b"] # comment\n'.encode()]:
            result = tomllib.loads(install.plan_bar(raw).decode())
            original = tomllib.loads(raw.decode())
            self.assertEqual(result, dict(original, left=['winagotchi'] + original['left']))

    def test_inserts_immediately_before_workspaces_preserving_other_positions(self):
        raw = b'left=["clock", "separator", "workspaces", "weather"]\nright=["wifi"]'
        result = tomllib.loads(install.plan_bar(raw).decode())
        self.assertEqual(result['left'], ['clock', 'separator', 'winagotchi', 'workspaces', 'weather'])
        self.assertEqual(result['right'], ['wifi'])

    def test_failure_rolls_back_applet_without_touching_bar(self):
        with patch.object(install, 'atomic', side_effect=OSError('fixture')):
            with self.assertRaises(OSError): self.run_install()
        self.assertEqual(self.bar.read_bytes(), self.original)
        self.assertFalse((self.config / 'applets/winagotchi').exists())
        self.assertEqual(list(self.root.glob('.winagotchi-stage-*')), [])

    def test_concurrent_bar_change_is_preserved(self):
        original_copy = install.shutil.copyfile
        def copying(source, target, **kwargs):
            result = original_copy(source, target, **kwargs)
            self.bar.write_bytes(self.original + b'# concurrent change\n')
            return result
        with patch.object(install.shutil, 'copyfile', side_effect=copying):
            with self.assertRaises(ValueError): self.run_install()
        self.assertTrue(self.bar.read_bytes().endswith(b'# concurrent change\n'))
        self.assertFalse((self.config / 'applets/winagotchi').exists())

    def test_invalid_binary_or_native_path_does_not_write(self):
        for native in ['relative/path', 'C:relative']:
            with self.assertRaises(ValueError): install.install(self.config, self.binary, native, self.backups)
        for content in [b'ELF', bytes(256), b'MZ' + bytes(254)]:
            self.binary.write_bytes(content)
            with self.assertRaises(ValueError): self.run_install()
        self.assertEqual(self.bar.read_bytes(), self.original)
        self.assertFalse(self.backups.exists())

    def test_backups_stay_outside_config_and_repo(self):
        for backup in [self.config / 'backups', ROOT / 'backups']:
            with self.assertRaises(ValueError):
                install.install(self.config, self.binary, r'C:\Config', backup)
            self.assertFalse(backup.exists())

    def test_bar_symlink_is_rejected(self):
        other = self.root / 'other.toml'; self.bar.rename(other); self.bar.symlink_to(other)
        with self.assertRaises(ValueError): self.run_install()
        self.assertEqual(other.read_bytes(), self.original)


if __name__ == '__main__': unittest.main()
