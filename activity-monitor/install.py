#!/usr/bin/env python3
"""Install the independent applet; never edit Winarchy source or Claude settings."""
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
FILES = ('applet.toml', 'view.slint', 'icon.svg', 'README.md', 'LICENSE')


def plan_bar(raw):
    text = raw.decode('utf-8')
    parsed = tomllib.loads(text.lstrip('\ufeff'))
    sections = {k: parsed.get(k, []) for k in ('left', 'center', 'right')}
    if any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in sections.values()):
        raise ValueError('Unsupported bar sections')
    if any('activity-monitor' in v for v in sections.values()):
        raise ValueError('Activity Monitor is already in the bar')
    expected = sum(x in ('cpu', 'memory') for v in sections.values() for x in v)
    if not expected:
        raise ValueError('No CPU or memory entries to replace; configure the bar manually')
    removed = 0

    def replace(match):
        nonlocal removed
        values = tomllib.loads('items = ' + match[3])['items']
        if not any(x in ('cpu', 'memory') for x in values):
            return match[0]
        result = []
        for value in values:
            if value in ('cpu', 'memory'):
                if not removed:
                    result.append('activity-monitor')
                removed += 1
            else:
                result.append(value)
        return match[1] + json.dumps(result, ensure_ascii=False)

    array = r'''\[(?:[^\]"'\r\n]|"(?:[^"\\\r\n]|\\.)*"|'[^'\r\n]*')*\]'''
    result = re.sub(r'(?m)^(\s*(left|center|right)\s*=\s*)(' + array + ')', replace, text)
    if removed != expected:
        raise ValueError('Multiline/complex bar arrays require manual migration; nothing changed')
    tomllib.loads(result.lstrip('\ufeff'))
    return result.encode('utf-8')


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        file.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(config, binary, windows_config, backup_root):
    config = Path(config)
    bar = config / 'bar.toml'
    target = config / 'applets/activity-monitor'
    if target.exists() or target.is_symlink():
        raise ValueError('Existing applet will not be overwritten; back it up and upgrade manually')
    if bar.is_symlink() or not bar.is_file():
        raise ValueError('bar.toml must be an existing regular file')
    original = bar.read_bytes()
    planned = plan_bar(original)
    binary = Path(binary)
    if binary.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Collector exceeds 32 MiB')
    image = binary.read_bytes()
    if len(image) < 64 or image[:2] != b'MZ':
        raise ValueError('Build the Windows collector first (not a Linux binary)')
    offset = struct.unpack_from('<I', image, 0x3c)[0]
    if image[offset:offset+6] != b'PE\0\0\x64\x86':
        raise ValueError('Expected an x86-64 Windows PE executable')
    windows_config = PureWindowsPath(windows_config)
    if not windows_config.is_absolute():
        raise ValueError('Windows configuration path must be absolute')
    program = str(windows_config / 'applets/activity-monitor/activity-monitor.exe')
    manifest = (ROOT/'applet.toml').read_text()
    # A callable preserves Windows backslashes literally.
    manifest, count = re.subn(r'(?m)^command = .*$', lambda _: 'command = ' + json.dumps([program]), manifest)
    if count != 1 or tomllib.loads(manifest)['command'] != [program]:
        raise ValueError('Invalid provider command')
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='activity-install-', dir=backup_root))
    (backup/'bar.toml').write_bytes(original)
    (backup/'bar.toml').chmod(0o600)
    # Stage beside, not inside, Winarchy's watched configuration directory.
    stage = Path(tempfile.mkdtemp(prefix='.activity-stage-', dir=config.parent))
    published = False
    written = False
    try:
        for name in FILES:
            shutil.copyfile(ROOT/name, stage/name)
        (stage/'applet.toml').write_text(manifest, encoding='utf-8')
        (stage/'activity-monitor.exe').write_bytes(image)
        if bar.read_bytes() != original or target.exists() or target.is_symlink():
            raise ValueError('Configuration changed during installation; retry after reviewing it')
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(target)
        published = True
        # The applet is complete before the bar can refer to it.
        if bar.read_bytes() != original:
            raise ValueError('Bar changed during installation')
        atomic(bar, planned)
        written = True
        return {'applet': str(target), 'backup': str(backup)}
    except Exception:
        if written and bar.read_bytes() == planned:
            atomic(bar, original)
        if published:
            shutil.rmtree(target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path, help='Winarchy configuration directory (WSL path)')
    parser.add_argument('--binary', type=Path, default=ROOT/'collector/target/x86_64-pc-windows-msvc/release/activity-monitor.exe')
    parser.add_argument('--windows-config', help='Native Windows spelling; defaults to wslpath -w')
    parser.add_argument('--backup-root', type=Path, default=Path.home()/'.local/state/winarchy-applet-collection/backups')
    args = parser.parse_args()
    native = args.windows_config or subprocess.check_output(['wslpath', '-w', str(args.config.resolve())], text=True).strip()
    print(json.dumps(install(args.config, args.binary, native, args.backup_root), indent=2))


if __name__ == '__main__':
    main()
