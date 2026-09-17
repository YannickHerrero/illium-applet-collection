#!/usr/bin/env python3
"""Install the Herdr applet from WSL, preserving the existing bar configuration."""
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
FILES = ('view.slint', 'icon.svg', 'README.md')
SCRIPT = 'herdr-agents.sh'


def patched_bar(raw):
    text = raw.decode('utf-8-sig')
    data = tomllib.loads(text)
    modules = data.get('right')
    if not isinstance(modules, list) or not all(isinstance(x, str) for x in modules):
        raise ValueError('bar.toml needs a right-hand module array')
    if 'herdr' in sum((data.get(k, []) for k in ('left', 'center', 'right')), []):
        raise ValueError('herdr is already referenced by the bar')
    matches = list(re.finditer(r'(?m)^right[ \t]*=[ \t]*\[[^\]\n]*\]', text))
    if len(matches) != 1:
        raise ValueError('Automatic installation requires a single-line right array; configure a multiline bar manually')
    match = matches[0]
    result = text[:match.start()] + 'right = ' + json.dumps(modules + ['herdr']) + text[match.end():]
    if tomllib.loads(result) != dict(data, right=modules + ['herdr']):
        raise ValueError('Bar edit changed unexpected configuration')
    return result.encode('utf-8')


def patched_manifest(distribution, script):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', distribution):
        raise ValueError('Unsupported WSL distribution name')
    command = ['wsl.exe', '-d', distribution, '--', 'bash', str(script)]
    text = (ROOT / 'applet.toml').read_text(encoding='utf-8')
    result, count = re.subn(r'(?m)^command = .*$', lambda _: 'command = ' + json.dumps(command), text)
    if count != 1 or tomllib.loads(result)['command'] != command:
        raise ValueError('Invalid provider command')
    return result.encode('utf-8')


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.install-', delete=False) as f:
            temporary = f.name
            f.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def install(config_home, distribution, local_home):
    target = config_home / 'applets/herdr'
    runtime = local_home / '.local/share/winarchy-applets/herdr'
    bar_path = config_home / 'bar.toml'
    if target.exists() or target.is_symlink() or runtime.exists():
        raise ValueError('An applet or script installation already exists; refusing to overwrite it')
    if bar_path.is_symlink() or not bar_path.is_file():
        raise ValueError('bar.toml must be an existing regular file')
    original_bar = bar_path.read_bytes()
    new_bar = patched_bar(original_bar)
    manifest = patched_manifest(distribution, runtime / SCRIPT)
    # Backups are private, outside Git and outside the watched Winarchy configuration.
    backup_root = local_home / '.local/state/winarchy-applet-collection/backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('herdr-install-%Y%m%d-%H%M%S-'), dir=backup_root))
    (backup / 'bar.toml').write_bytes(original_bar)
    created = []
    written = False
    try:
        runtime.mkdir(parents=True)
        created.append(runtime)
        shutil.copyfile(ROOT / SCRIPT, runtime / SCRIPT)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Stage beside, not inside, Winarchy's watched configuration directory,
        # and publish a complete folder before the bar refers to it.
        stage = Path(tempfile.mkdtemp(prefix='.herdr-install-', dir=config_home.parent))
        try:
            for name in FILES:
                shutil.copyfile(ROOT / name, stage / name)
            (stage / 'applet.toml').write_bytes(manifest)
            if bar_path.read_bytes() != original_bar or target.exists() or target.is_symlink():
                raise ValueError('Configuration changed concurrently; installation cancelled')
            stage.rename(target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        created.append(target)
        if bar_path.read_bytes() != original_bar:
            raise ValueError('Configuration changed concurrently; installation cancelled')
        atomic_write(bar_path, new_bar)
        written = True
    except Exception:
        if written and bar_path.read_bytes() == new_bar:
            atomic_write(bar_path, original_bar)
        for path in reversed(created):
            shutil.rmtree(path)
        raise
    result = {'backup': str(backup), 'applet': str(target), 'script': str(runtime / SCRIPT), 'distribution': distribution}
    (backup / 'installation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-home', type=Path, help='WSL-visible Windows profile, e.g. /mnt/c/Users/Name')
    parser.add_argument('--config-home', type=Path, help='WSL-visible Winarchy configuration directory, if not <windows home>/.config/winarchy')
    parser.add_argument('--distribution', default=os.environ.get('WSL_DISTRO_NAME', ''), help='WSL distribution running herdr (default: the current one)')
    args = parser.parse_args()
    if not args.config_home and not args.windows_home:
        parser.error('--windows-home or --config-home is required')
    if not args.distribution:
        parser.error('--distribution is required outside WSL')
    os.umask(0o077)
    try:
        result = install(args.config_home or args.windows_home / '.config/winarchy', args.distribution, Path.home())
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
