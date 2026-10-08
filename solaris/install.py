#!/usr/bin/env python3
"""Install the Solaris applet from WSL, preserving the existing bar configuration."""
import argparse
import datetime
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
NAME = 'solaris'
FILES = ('view.slint', 'icon.svg', 'README.md')
PROVIDER = ROOT / 'provider/target/x86_64-pc-windows-msvc/release/solaris-applet.exe'


def patched_bar(raw):
    """Opens the drawer with the applet when the bar has one, otherwise appends
    it to `right`."""
    text = raw.decode('utf-8-sig')
    data = tomllib.loads(text)
    key = 'drawer' if isinstance(data.get('drawer'), list) else 'right'
    modules = data.get(key)
    if not isinstance(modules, list) or not all(isinstance(x, str) for x in modules):
        raise ValueError(f'bar.toml needs a {key} module array')
    if NAME in sum((data.get(k, []) for k in ('left', 'center', 'right', 'drawer')), []):
        raise ValueError(f'{NAME} is already referenced by the bar')
    matches = list(re.finditer(rf'(?m)^{key}[ \t]*=[ \t]*\[[^\]\n]*\]', text))
    if len(matches) != 1:
        raise ValueError(f'Automatic installation requires a single-line {key} array; configure a multiline bar manually')
    updated = [NAME] + modules if key == 'drawer' else modules + [NAME]
    match = matches[0]
    result = text[:match.start()] + f'{key} = ' + json.dumps(updated) + text[match.end():]
    if tomllib.loads(result) != dict(data, **{key: updated}):
        raise ValueError('Bar edit changed unexpected configuration')
    return result.encode('utf-8')


def windows_executable(path):
    image = Path(path).read_bytes()
    if len(image) < 64 or image[:2] != b'MZ':
        raise ValueError('Build the Windows provider first, not a Linux binary')
    offset = struct.unpack_from('<I', image, 0x3c)[0]
    if image[offset:offset + 6] != b'PE\0\0\x64\x86':
        raise ValueError('Expected an x86-64 Windows PE executable')
    return image


def patched_manifest(windows_config):
    native = PureWindowsPath(windows_config)
    if not native.is_absolute():
        raise ValueError('Windows configuration path must be absolute')
    command = [str(native / 'applets' / NAME / PROVIDER.name)]
    text = (ROOT / 'applet.toml').read_text(encoding='utf-8')
    result, count = re.subn(r'(?m)^command = .*$', lambda _: 'command = ' + json.dumps(command), text)
    if count != 1 or tomllib.loads(result)['command'] != command:
        raise ValueError('Invalid provider command')
    return result.encode('utf-8')


def atomic_write(path, data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.install-', delete=False) as f:
            temporary = f.name
            f.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def install(config_home, windows_config, local_home, provider=PROVIDER):
    target = config_home / 'applets' / NAME
    bar_path = config_home / 'bar.toml'
    if target.exists() or target.is_symlink():
        raise ValueError('An applet installation already exists; refusing to overwrite it')
    if bar_path.is_symlink() or not bar_path.is_file():
        raise ValueError('bar.toml must be an existing regular file')
    image = windows_executable(provider)
    original_bar = bar_path.read_bytes()
    new_bar = patched_bar(original_bar)
    manifest = patched_manifest(windows_config)
    # Backups are private, outside Git and outside the watched Illium configuration.
    backup_root = local_home / '.local/state/illium-applet-collection/backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime(f'{NAME}-install-%Y%m%d-%H%M%S-'), dir=backup_root))
    (backup / 'bar.toml').write_bytes(original_bar)
    published = False
    written = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Stage beside, not inside, Illium's watched configuration directory,
        # and publish a complete folder before the bar refers to it.
        stage = Path(tempfile.mkdtemp(prefix=f'.{NAME}-install-', dir=config_home.parent))
        try:
            for name in FILES:
                shutil.copyfile(ROOT / name, stage / name)
            (stage / 'applet.toml').write_bytes(manifest)
            (stage / PROVIDER.name).write_bytes(image)
            if bar_path.read_bytes() != original_bar or target.exists() or target.is_symlink():
                raise ValueError('Configuration changed concurrently; installation cancelled')
            stage.rename(target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        published = True
        if bar_path.read_bytes() != original_bar:
            raise ValueError('Configuration changed concurrently; installation cancelled')
        atomic_write(bar_path, new_bar)
        written = True
    except Exception:
        if written and bar_path.read_bytes() == new_bar:
            atomic_write(bar_path, original_bar)
        if published:
            shutil.rmtree(target)
        raise
    result = {'backup': str(backup), 'applet': str(target)}
    (backup / 'installation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-home', type=Path, help='WSL-visible Windows profile, e.g. /mnt/c/Users/Name')
    parser.add_argument('--config-home', type=Path, help='WSL-visible Illium configuration directory, if not <windows home>/.config/illium')
    parser.add_argument('--windows-config', help='Native Windows spelling of the configuration directory; defaults to wslpath -w')
    args = parser.parse_args()
    if not args.config_home and not args.windows_home:
        parser.error('--windows-home or --config-home is required')
    os.umask(0o077)
    try:
        config = args.config_home or args.windows_home / '.config/illium'
        native = args.windows_config or subprocess.check_output(['wslpath', '-w', str(config.resolve())], text=True).strip()
        result = install(config, native, Path.home())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
