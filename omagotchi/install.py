#!/usr/bin/env python3
"""Install Omagotchi from WSL; no engine changes, services, or audio."""
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
FILES = ('applet.toml', 'view.slint', 'sprites.slint', 'README.md', 'LICENSE', 'SOURCES.md')
NAME = 'omagotchi'


def plan_bar(raw):
    text = raw.decode('utf-8')
    data = tomllib.loads(text.lstrip('\ufeff'))
    sections = [data.get(key, []) for key in ('left', 'center', 'right')]
    if any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in sections):
        raise ValueError('Bar sections must be arrays of module names')
    if any(NAME in section for section in sections):
        raise ValueError('Omagotchi is already referenced by the bar')
    if 'right' not in data:
        raise ValueError('bar.toml needs a right module array')
    # Parse TOML first, then only patch a simple single-line array. Compare
    # complete parsed documents afterwards: quoted brackets/comments are safe.
    array = r'''\[(?:[^\]"'\r\n]|"(?:[^"\\\r\n]|\\.)*"|'[^'\r\n]*')*\]'''
    matches = list(re.finditer(r'(?m)^([ \t\ufeff]*right[ \t]*=[ \t]*)(' + array + ')', text))
    if len(matches) != 1:
        raise ValueError('A multiline/complex right array requires manual installation')
    match = matches[0]
    updated = data['right'] + [NAME]
    result = text[:match.start(2)] + json.dumps(updated, ensure_ascii=False) + text[match.end(2):]
    if tomllib.loads(result.lstrip('\ufeff')) != dict(data, right=updated):
        raise ValueError('Bar edit changed unexpected configuration')
    return result.encode('utf-8')


def atomic(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.omagotchi-', delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install(config, binary, windows_config, backup_root):
    config = Path(config).resolve()
    bar = config / 'bar.toml'
    target = config / 'applets' / NAME
    if target.exists() or target.is_symlink():
        raise ValueError('Existing Omagotchi will not be overwritten; back it up and upgrade manually')
    if bar.is_symlink() or not bar.is_file():
        raise ValueError('bar.toml must be an existing regular file')
    if target.parent.is_symlink():
        raise ValueError('The applets directory must not be a symlink')
    original = bar.read_bytes()
    planned = plan_bar(original)
    binary = Path(binary)
    if binary.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Provider exceeds 32 MiB')
    image = binary.read_bytes()
    if len(image) < 64 or image[:2] != b'MZ':
        raise ValueError('Build the Windows provider first, not a Linux binary')
    offset = struct.unpack_from('<I', image, 0x3c)[0]
    if image[offset:offset + 6] != b'PE\0\0\x64\x86':
        raise ValueError('Expected an x86-64 Windows PE executable')
    native = PureWindowsPath(windows_config)
    if not native.is_absolute():
        raise ValueError('Windows configuration path must be absolute')
    program = str(native / 'applets' / NAME / 'omagotchi.exe')
    manifest, count = re.subn(r'(?m)^command = .*$', lambda _: 'command = ' + json.dumps([program]),
                              (ROOT / 'applet.toml').read_text())
    if count != 1 or tomllib.loads(manifest)['command'] != [program]:
        raise ValueError('Invalid provider manifest')
    backup_root = Path(backup_root).resolve()
    if backup_root.is_relative_to(config) or backup_root.is_relative_to(ROOT.parent):
        raise ValueError('Backups must be outside the configuration tree and this repository')
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='omagotchi-install-', dir=backup_root))
    (backup / 'bar.toml').write_bytes(original)
    (backup / 'bar.toml').chmod(0o600)
    # Publish a complete directory before adding its name to the bar.
    stage = Path(tempfile.mkdtemp(prefix='.omagotchi-stage-', dir=config.parent))
    published = False
    try:
        for name in FILES:
            shutil.copyfile(ROOT / name, stage / name)
        for icon in ROOT.glob('*.png'):
            shutil.copyfile(icon, stage / icon.name)
        shutil.copytree(ROOT / 'assets', stage / 'assets')
        (stage / 'applet.toml').write_text(manifest, encoding='utf-8')
        (stage / 'omagotchi.exe').write_bytes(image)
        if bar.read_bytes() != original or target.exists() or target.is_symlink():
            raise ValueError('Configuration changed during installation; review it and retry')
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(target)
        published = True
        if bar.read_bytes() != original:
            raise ValueError('Bar changed during installation')
        atomic(bar, planned)
        return {'applet': str(target), 'backup': str(backup)}
    except Exception:
        if published:
            shutil.rmtree(target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--config', type=Path, help='Winarchy configuration directory, WSL spelling')
    group.add_argument('--windows-home', type=Path, help='WSL Windows profile; uses .config/winarchy')
    parser.add_argument('--binary', type=Path, default=ROOT / 'provider/target/x86_64-pc-windows-msvc/release/omagotchi.exe')
    parser.add_argument('--windows-config', help='Native Windows spelling; defaults to wslpath -w')
    parser.add_argument('--backup-root', type=Path, default=Path.home() / '.local/state/winarchy-applet-collection/backups')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config = args.config or args.windows_home / '.config/winarchy'
        native = args.windows_config or subprocess.check_output(['wslpath', '-w', str(config.resolve())], text=True).strip()
        result = install(config, args.binary, native, args.backup_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
