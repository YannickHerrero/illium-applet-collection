import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('herdr_install', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'linux'
        self.config = Path(self.temp.name) / 'windows/.config/winarchy'
        self.config.mkdir(parents=True)
        self.bar = b'height = 28\r\nleft = ["workspaces"]\r\nright = ["wifi", "claude-usage"] # retain ] comment\r\n'
        (self.config / 'bar.toml').write_bytes(self.bar)

    def install(self, distribution='Debian'):
        return installer.install(self.config, distribution, self.home)

    def test_copies_applet_and_script_and_appends_to_the_bar(self):
        result = self.install()
        text = (self.config / 'bar.toml').read_bytes()
        self.assertEqual(tomllib.loads(text.decode())['right'], ['wifi', 'claude-usage', 'herdr'])
        self.assertIn(b'# retain ] comment\r\n', text)
        self.assertIn(b'left = ["workspaces"]\r\n', text)
        self.assertEqual((Path(result['backup']) / 'bar.toml').read_bytes(), self.bar)
        applet = Path(result['applet'])
        for name in installer.FILES:
            self.assertTrue((applet / name).is_file())
        script = self.home / '.local/share/winarchy-applets/herdr/herdr-agents.sh'
        self.assertEqual(script.read_bytes(), (installer.ROOT / 'herdr-agents.sh').read_bytes())
        manifest = tomllib.loads((applet / 'applet.toml').read_text())
        self.assertEqual(manifest['command'], ['wsl.exe', '-d', 'Debian', '--', 'bash', str(script)])
        self.assertEqual(manifest['label'], '{bar_label}')
        self.assertEqual(list(self.config.parent.glob('.herdr-install-*')), [])

    def test_refuses_an_existing_installation_or_bad_distribution(self):
        with self.assertRaises(ValueError):
            self.install('Debian; rm')
        self.install()
        snapshot = (self.config / 'bar.toml').read_bytes()
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual((self.config / 'bar.toml').read_bytes(), snapshot)

    def test_failure_rolls_back_files_without_touching_the_bar(self):
        with patch.object(installer, 'atomic_write', side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.config / 'bar.toml').read_bytes(), self.bar)
        self.assertFalse((self.config / 'applets/herdr').exists())
        self.assertFalse((self.home / '.local/share/winarchy-applets/herdr').exists())

    def test_concurrent_bar_change_is_preserved(self):
        original_copy = installer.shutil.copyfile
        def copying(source, target):
            result = original_copy(source, target)
            (self.config / 'bar.toml').write_bytes(self.bar + b'# concurrent change\n')
            return result
        with patch.object(installer.shutil, 'copyfile', side_effect=copying):
            with self.assertRaises(ValueError):
                self.install()
        self.assertTrue((self.config / 'bar.toml').read_bytes().endswith(b'# concurrent change\n'))
        self.assertFalse((self.config / 'applets/herdr').exists())

    def test_multiline_or_duplicate_bar_requires_manual_setup(self):
        for raw in [b'right = [\n"wifi",\n]\n', b'right = ["herdr"]\n', b'left = ["herdr"]\nright = ["wifi"]\n']:
            with self.assertRaises(ValueError):
                installer.patched_bar(raw)


if __name__ == '__main__':
    unittest.main()
