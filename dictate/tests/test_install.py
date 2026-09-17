import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dictate_install', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'linux'
        self.config = Path(self.temp.name) / 'windows/.config/winarchy'
        self.config.mkdir(parents=True)
        self.bar = b'height = 28\r\nright = ["claude-usage", "separator", "activity-monitor", "separator", "wifi"] # keep ] me\r\n'
        (self.config / 'bar.toml').write_bytes(self.bar)

    def install(self):
        return installer.install(self.config, self.home)

    def test_places_the_applet_before_wifi(self):
        result = self.install()
        text = (self.config / 'bar.toml').read_bytes()
        self.assertEqual(tomllib.loads(text.decode())['right'], ['claude-usage', 'separator', 'activity-monitor', 'separator', 'dictate', 'wifi'])
        self.assertIn(b'# keep ] me\r\n', text)
        self.assertEqual((Path(result['backup']) / 'bar.toml').read_bytes(), self.bar)
        for name in installer.FILES:
            self.assertTrue((Path(result['applet']) / name).is_file())
        self.assertEqual(list(self.config.parent.glob('.dictate-install-*')), [])

    def test_appends_without_wifi(self):
        changed = tomllib.loads(installer.patched_bar(b'right = ["volume", "battery"]\n').decode())
        self.assertEqual(changed['right'], ['volume', 'battery', 'dictate'])

    def test_refuses_existing_or_multiline(self):
        self.install()
        with self.assertRaises(ValueError):
            self.install()
        for raw in [b'right = [\n"wifi",\n]\n', b'center = ["dictate"]\nright = ["wifi"]\n']:
            with self.assertRaises(ValueError):
                installer.patched_bar(raw)

    def test_failure_rolls_back(self):
        with patch.object(installer, 'atomic_write', side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.config / 'bar.toml').read_bytes(), self.bar)
        self.assertFalse((self.config / 'applets/dictate').exists())


if __name__ == '__main__':
    unittest.main()
