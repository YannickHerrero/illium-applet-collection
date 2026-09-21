import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('agenda_install', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
BAR = b'# preserved\nleft = ["workspaces"]\ncenter = ["clock"]\nright = ["battery", "wifi"] # comment\n'


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.config/winarchy'
        self.config.mkdir(parents=True)
        (self.config / 'bar.toml').write_bytes(BAR)
        calendar = self.config / 'applets/calendar'
        calendar.mkdir(parents=True)
        (calendar / 'view.slint').write_text('untouched')

    def install(self):
        return installer.install(self.config, self.home)

    def test_install_and_idempotence(self):
        first = self.install()
        target = Path(first['applet'])
        self.assertTrue((target / 'connectors/outlook.ps1').is_file())
        self.assertEqual((Path(first['backup']) / 'bar.toml').read_bytes(), BAR)
        data = tomllib.loads((self.config / 'bar.toml').read_text())
        self.assertEqual(data['center'], ['clock'])
        self.assertEqual(data['right'], ['battery', 'calendar-agenda', 'wifi'])
        self.assertEqual((self.config / 'applets/calendar/view.slint').read_text(), 'untouched')
        self.assertTrue(self.install()['unchanged'])

    def test_update_backs_up_and_preserves_extras(self):
        target = Path(self.install()['applet'])
        (target / 'lib.ps1').write_text('old')
        (target / 'notes.txt').write_text('personal note')
        result = self.install()
        self.assertFalse(result['unchanged'])
        self.assertEqual((Path(result['backup']) / 'calendar-agenda/lib.ps1').read_text(), 'old')
        self.assertEqual((target / 'notes.txt').read_text(), 'personal note')
        self.assertEqual((target / 'lib.ps1').read_bytes(), (ROOT / 'lib.ps1').read_bytes())

    def test_existing_entry_any_section(self):
        raw = b'left = ["calendar-agenda"]\ncenter = ["clock"]\nright = []\n'
        self.assertEqual(installer.patched_bar(raw), raw)

    def test_multiline_is_not_rewritten(self):
        with self.assertRaises(ValueError):
            installer.patched_bar(b'right = [\n "wifi"\n]\n')

    def test_symlink_refused(self):
        (self.config / 'applets/calendar-agenda').symlink_to(self.config / 'applets/calendar', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual((self.config / 'bar.toml').read_bytes(), BAR)

    def test_write_failure_rolls_back(self):
        with patch.object(installer, 'atomic_write', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                self.install()
        self.assertFalse((self.config / 'applets/calendar-agenda').exists())
        self.assertEqual((self.config / 'bar.toml').read_bytes(), BAR)


if __name__ == '__main__':
    unittest.main()
