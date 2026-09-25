import importlib.util
from pathlib import Path
import struct
import tempfile
import tomllib
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('activity_install',Path(__file__).resolve().parents[1]/'install.py')
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'config';self.config.mkdir()
        self.bar=self.config/'bar.toml'
        self.original=b'# Preserve me\r\nleft = ["workspaces"]\r\nright = ["cpu", "memory", "wifi", "claude-usage"] # keep ] here\r\nclock_format = "%A %d %b"\r\n'
        self.bar.write_bytes(self.original)
        image=bytearray(256);image[:2]=b'MZ';struct.pack_into('<I',image,0x3c,128);image[128:134]=b'PE\0\0\x64\x86'
        self.binary=self.root/'collector.exe';self.binary.write_bytes(image)
        self.backups=self.root/'backups'
    def run_install(self):
        return install.install(self.config,self.binary,r'C:\Users\Test User\.config\illium',self.backups)
    def test_preserves_other_modules_comments_and_windows_path(self):
        result=self.run_install()
        self.assertEqual(tomllib.loads(self.bar.read_text())['right'],['activity-monitor','wifi','claude-usage'])
        self.assertIn(b'# keep ] here\r\n',self.bar.read_bytes())
        self.assertIn(b'clock_format = "%A %d %b"\r\n',self.bar.read_bytes())
        self.assertEqual((Path(result['backup'])/'bar.toml').read_bytes(),self.original)
        app=Path(result['applet']);manifest=tomllib.loads((app/'applet.toml').read_text())
        self.assertEqual(manifest['command'],[r'C:\Users\Test User\.config\illium\applets\activity-monitor\activity-monitor.exe'])
        self.assertEqual((app/'activity-monitor.exe').read_bytes(),self.binary.read_bytes())
    def test_replaces_across_sections_once(self):
        raw=b'left = ["memory", "clock"]\nright = ["cpu", "wifi"]\n'
        changed=tomllib.loads(install.plan_bar(raw).decode())
        self.assertEqual(changed,dict(left=['activity-monitor','clock'],right=['wifi']))
    def test_existing_installation_is_never_overwritten(self):
        self.run_install();snapshot=self.bar.read_bytes()
        with self.assertRaises(ValueError):self.run_install()
        self.assertEqual(self.bar.read_bytes(),snapshot)
    def test_multiline_or_missing_modules_require_manual_migration(self):
        for raw in [b'right = [\n"cpu",\n"memory"\n]\n',b'right = ["wifi"]\n',b'right = ["activity-monitor", "cpu"]\n']:
            with self.assertRaises(ValueError):install.plan_bar(raw)
    def test_failure_rolls_back_new_applet_without_touching_bar(self):
        with patch.object(install,'atomic',side_effect=OSError('fixture')):
            with self.assertRaises(OSError):self.run_install()
        self.assertEqual(self.bar.read_bytes(),self.original)
        self.assertFalse((self.config/'applets/activity-monitor').exists())
        self.assertEqual(list(self.root.glob('.activity-stage-*')),[])
    def test_concurrent_bar_change_is_preserved(self):
        original_copy=install.shutil.copyfile
        def copying(source,target):
            result=original_copy(source,target)
            self.bar.write_bytes(self.original+b'# concurrent change\n')
            return result
        with patch.object(install.shutil,'copyfile',side_effect=copying):
            with self.assertRaises(ValueError):self.run_install()
        self.assertTrue(self.bar.read_bytes().endswith(b'# concurrent change\n'))
        self.assertFalse((self.config/'applets/activity-monitor').exists())
    def test_wrong_binary_does_not_change_anything(self):
        self.binary.write_bytes(b'ELF, not Windows')
        with self.assertRaises(ValueError):self.run_install()
        self.assertEqual(self.bar.read_bytes(),self.original)
        self.assertFalse(self.backups.exists())

if __name__=='__main__':unittest.main()
