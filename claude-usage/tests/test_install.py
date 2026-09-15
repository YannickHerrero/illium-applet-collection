import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'install.py'
spec = importlib.util.spec_from_file_location('installer', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'linux'
        self.windows = Path(self.temp.name) / 'windows'
        self.claude = self.home / '.claude'
        self.config = self.windows / '.config/winarchy'
        self.claude.mkdir(parents=True)
        self.config.mkdir(parents=True)
        self.original = {'statusLine': {'type': 'command', 'command': '~/.claude/statusline.sh', 'padding': 2}, 'unrelated': {'keep': True}}
        (self.claude / 'settings.json').write_text(json.dumps(self.original))
        self.bar = b'height = 28\nleft = ["workspaces"]\nright = ["wifi"] # retain comment\n'
        (self.config / 'bar.toml').write_bytes(self.bar)

    def install(self):
        return installer.install(self.windows, self.config, self.claude, self.home)

    def test_preserves_configuration_and_original_delegate(self):
        result = self.install()
        settings = json.loads((self.claude / 'settings.json').read_text())
        self.assertEqual(settings['unrelated'], self.original['unrelated'])
        self.assertEqual(settings['statusLine']['padding'], 2)
        self.assertIn('bridge.py', settings['statusLine']['command'])
        relay = json.loads((Path(result['relay']) / 'bridge.json').read_text())
        self.assertEqual(relay['delegate'], self.original['statusLine']['command'])
        self.assertEqual(tomllib.loads((self.config / 'bar.toml').read_text())['right'], ['wifi', 'claude-usage'])
        self.assertIn('# retain comment', (self.config / 'bar.toml').read_text())
        self.assertEqual((Path(result['backup']) / 'bar.toml').read_bytes(), self.bar)
        for name in installer.FILES:
            self.assertTrue((Path(result['applet']) / name).is_file())

    def test_refuses_an_existing_installation(self):
        self.install()
        with self.assertRaises(ValueError):
            self.install()

    def test_failure_rolls_back_live_settings(self):
        original = (self.claude / 'settings.json').read_bytes()
        write = installer.atomic_write
        def fail_bar(path, content):
            if path.name == 'bar.toml':
                raise OSError('simulated write failure')
            write(path, content)
        with patch.object(installer, 'atomic_write', side_effect=fail_bar):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.claude / 'settings.json').read_bytes(), original)
        self.assertEqual((self.config / 'bar.toml').read_bytes(), self.bar)
        self.assertFalse((self.config / 'applets/claude-usage').exists())
        self.assertFalse((self.home / '.local/share/winarchy-applets/claude-usage').exists())

    def test_multiline_bar_requires_manual_setup(self):
        with self.assertRaises(ValueError):
            installer.patched_bar(b'right = [\n"wifi",\n]\n')


if __name__ == '__main__':
    unittest.main()
