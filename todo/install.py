#!/usr/bin/env python3
"""Install the Todo applet from WSL, preserving the existing bar configuration."""
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
FILES = ('applet.toml', 'view.slint', 'icon.svg', 'check.svg', 'plus.svg', 'trash.svg', 'todo.ps1', 'README.md')
NAME = 'todo'


def patched_bar(raw):
    """Opens the drawer with the applet when the bar has one, since a list you
    read on purpose belongs behind the chevron rather than among the permanent
    indicators; without a drawer, places it before claude-usage in `right`."""
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
    if key == 'drawer':
        position = 0
    else:
        position = modules.index('claude-usage') if 'claude-usage' in modules else len(modules)
    updated = modules[:position] + [NAME] + modules[position:]
    match = matches[0]
    result = text[:match.start()] + f'{key} = ' + json.dumps(updated) + text[match.end():]
    if tomllib.loads(result) != dict(data, **{key: updated}):
        raise ValueError('Bar edit changed unexpected configuration')
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


def install(config_home, local_home):
    target = config_home / 'applets' / NAME
    bar_path = config_home / 'bar.toml'
    if target.exists() or target.is_symlink():
        raise ValueError('An applet installation already exists; refusing to overwrite it')
    if bar_path.is_symlink() or not bar_path.is_file():
        raise ValueError('bar.toml must be an existing regular file')
    original_bar = bar_path.read_bytes()
    new_bar = patched_bar(original_bar)
    backup_root = local_home / '.local/state/winarchy-applet-collection/backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime(f'{NAME}-install-%Y%m%d-%H%M%S-'), dir=backup_root))
    (backup / 'bar.toml').write_bytes(original_bar)
    published = False
    written = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Stage beside, not inside, Winarchy's watched configuration directory,
        # and publish a complete folder before the bar refers to it.
        stage = Path(tempfile.mkdtemp(prefix=f'.{NAME}-install-', dir=config_home.parent))
        try:
            for name in FILES:
                shutil.copyfile(ROOT / name, stage / name)
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
    parser.add_argument('--config-home', type=Path, help='WSL-visible Winarchy configuration directory, if not <windows home>/.config/winarchy')
    args = parser.parse_args()
    if not args.config_home and not args.windows_home:
        parser.error('--windows-home or --config-home is required')
    os.umask(0o077)
    try:
        result = install(args.config_home or args.windows_home / '.config/winarchy', Path.home())
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
