import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

spec = importlib.util.spec_from_file_location('solaris_install', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

# Smallest image the PE check accepts: MZ, e_lfanew = 64, PE signature, AMD64.
PE = b'MZ' + b'\0' * 58 + (64).to_bytes(4, 'little') + b'PE\0\0\x64\x86'
WINDOWS_CONFIG = 'C:\\Users\\me\\.config\\illium'


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / 'linux'
        self.config = root / 'windows/.config/illium'
        self.config.mkdir(parents=True)
        self.provider = root / 'build/solaris-applet.exe'
        self.provider.parent.mkdir()
        self.provider.write_bytes(PE)

    def install(self, bar):
        (self.config / 'bar.toml').write_bytes(bar)
        return installer.install(self.config, WINDOWS_CONFIG, self.home, self.provider)

    def test_opens_the_drawer_with_the_applet_and_runs_the_copied_provider(self):
        bar = b'left = ["workspaces"]\r\nright = ["drawer", "battery"]\r\ndrawer = ["todo", "wifi"] # keep ] comment\r\n'
        result = self.install(bar)
        text = (self.config / 'bar.toml').read_bytes()
        self.assertEqual(tomllib.loads(text.decode())['drawer'], ['solaris', 'todo', 'wifi'])
        self.assertIn(b'# keep ] comment\r\n', text)
        self.assertEqual((Path(result['backup']) / 'bar.toml').read_bytes(), bar)
        applet = Path(result['applet'])
        for name in installer.FILES:
            self.assertTrue((applet / name).is_file())
        self.assertEqual((applet / 'solaris-applet.exe').read_bytes(), PE)
        manifest = tomllib.loads((applet / 'applet.toml').read_text())
        self.assertEqual(manifest['command'], [WINDOWS_CONFIG + '\\applets\\solaris\\solaris-applet.exe'])
        self.assertEqual(list(self.config.parent.glob('.solaris-install-*')), [])

    def test_appends_to_the_right_without_a_drawer(self):
        self.install(b'right = ["wifi"]\n')
        self.assertEqual(tomllib.loads((self.config / 'bar.toml').read_text())['right'], ['wifi', 'solaris'])

    def test_refuses_a_linux_provider_and_an_existing_installation(self):
        bar = b'right = ["wifi"]\n'
        self.provider.write_bytes(b'\x7fELF' + b'\0' * 80)
        with self.assertRaises(ValueError):
            self.install(bar)
        self.assertFalse((self.config / 'applets/solaris').exists())
        self.provider.write_bytes(PE)
        self.install(bar)
        snapshot = (self.config / 'bar.toml').read_bytes()
        with self.assertRaises(ValueError):
            self.install(snapshot)
        self.assertEqual((self.config / 'bar.toml').read_bytes(), snapshot)


if __name__ == '__main__':
    unittest.main()
