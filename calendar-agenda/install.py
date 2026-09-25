#!/usr/bin/env python3
"""Install/update Calendar Agenda independently, preserving clock and other applets."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
NAME = 'calendar-agenda'
FILES = ('applet.toml', 'icon.svg', 'refresh.svg', 'view.slint', 'agenda.ps1', 'lib.ps1',
         'worker.ps1', 'connectors/outlook.ps1', 'README.md')


def patched_bar(raw):
    text = raw.decode('utf-8-sig')
    data = tomllib.loads(text)
    for section in ('left', 'center', 'right'):
        if NAME in data.get(section, []):
            return raw
    modules = data.get('right')
    if not isinstance(modules, list) or not all(isinstance(x, str) for x in modules):
        raise ValueError('bar.toml needs a right-hand module array')
    matches = list(re.finditer(r'(?m)^right[ \t]*=[ \t]*\[[^\]\n]*\]', text))
    if len(matches) != 1:
        raise ValueError('Automatic installation needs a single-line right array; add calendar-agenda manually for multiline arrays')
    position = modules.index('wifi') if 'wifi' in modules else len(modules)
    updated = modules[:position] + [NAME] + modules[position:]
    match = matches[0]
    result = text[:match.start()] + 'right = ' + json.dumps(updated) + text[match.end():]
    if tomllib.loads(result) != dict(data, right=updated):
        raise ValueError('Unexpected bar configuration change')
    return result.encode('utf-8')


def atomic_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.install-', delete=False) as stream:
            temporary = stream.name
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def install(config_home, local_home):
    config_home = Path(config_home)
    target = config_home / 'applets' / NAME
    bar = config_home / 'bar.toml'
    if bar.is_symlink() or not bar.is_file():
        raise ValueError('bar.toml must be an existing regular file')
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError('Applet target must be a directory, not a symlink')
    if target.exists() and any(p.is_symlink() for p in target.rglob('*')):
        raise ValueError('Refusing to overwrite an applet containing symlinks')
    original = bar.read_bytes()
    updated = patched_bar(original)
    # The manifest contains user settings (clock attachment, size, interval).
    # Supply defaults on first install, but never reset an existing manifest.
    contents = {name: (ROOT / name).read_bytes() for name in FILES}
    manifest = target / 'applet.toml'
    if manifest.is_file():
        contents['applet.toml'] = manifest.read_bytes()
    if target.is_dir() and original == updated and all(
            (target / f).is_file() and (target / f).read_bytes() == contents[f] for f in FILES):
        return {'applet': str(target), 'unchanged': True}
    backup_root = Path(local_home) / '.local/state/illium-applet-collection/backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime(NAME + '-%Y%m%d-%H%M%S-'), dir=backup_root))
    (backup / 'bar.toml').write_bytes(original)
    existed = target.exists()
    if existed:
        shutil.copytree(target, backup / NAME)
    # Stage outside the watched config tree; preserve extra user files on updates.
    stage_root = Path(tempfile.mkdtemp(prefix='.' + NAME + '-', dir=config_home.parent))
    stage = stage_root / NAME
    previous = stage_root / 'previous'
    published = False
    moved = False
    written = False
    try:
        if existed:
            shutil.copytree(target, stage)
        else:
            stage.mkdir()
        for name in FILES:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents[name])
        if bar.read_bytes() != original or target.exists() != existed:
            raise ValueError('Configuration changed concurrently; installation cancelled')
        target.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            target.rename(previous)
            moved = True
        stage.rename(target)
        published = True
        if bar.read_bytes() != original:
            raise ValueError('Configuration changed concurrently; installation cancelled')
        if updated != original:
            atomic_write(bar, updated)
            written = True
    except Exception:
        if written and bar.read_bytes() == updated:
            atomic_write(bar, original)
        if published:
            shutil.rmtree(target)
        if moved:
            previous.rename(target)
        raise
    finally:
        shutil.rmtree(stage_root)
    return {'applet': str(target), 'backup': str(backup), 'unchanged': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-home', type=Path)
    parser.add_argument('--config-home', type=Path)
    args = parser.parse_args()
    if not args.windows_home and not args.config_home:
        parser.error('--windows-home or --config-home is required')
    os.umask(0o077)
    try:
        result = install(args.config_home or args.windows_home / '.config/illium', Path.home())
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
