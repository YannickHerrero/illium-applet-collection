#!/usr/bin/env python3
"""Install the Claude usage applet from WSL, preserving existing user configuration."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
FILES = ('applet.toml', 'view.slint', 'icon.svg', 'claude-usage.ps1')


def patched_bar(raw):
    text = raw.decode('utf-8-sig')
    data = tomllib.loads(text)
    modules = data.get('right')
    if not isinstance(modules, list) or not all(isinstance(x, str) for x in modules):
        raise ValueError('bar.toml needs a right-hand module array')
    if 'claude-usage' in sum((data.get(k, []) for k in ('left', 'center', 'right')), []):
        raise ValueError('claude-usage is already referenced by the bar')
    pattern = r'(?m)^right[ \t]*=[ \t]*\[[^\]\n]*\]'
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError('Automatic installation requires a single-line right array; configure a multiline bar manually')
    match = matches[0]
    result = text[:match.start()] + 'right = ' + json.dumps(modules + ['claude-usage']) + text[match.end():]
    expected = dict(data, right=modules + ['claude-usage'])
    if tomllib.loads(result) != expected:
        raise ValueError('Bar edit changed unexpected configuration')
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


def install(windows_home, config_home, claude_home, local_home):
    target = config_home / 'applets/claude-usage'
    runtime = local_home / '.local/share/winarchy-applets/claude-usage'
    settings_path = claude_home / 'settings.json'
    bar_path = config_home / 'bar.toml'
    if target.exists() or runtime.exists():
        raise ValueError('An applet or relay installation already exists; refusing to overwrite it')
    if not windows_home.is_dir() or not settings_path.is_file():
        raise ValueError('Windows home and existing Claude Code settings.json are required')
    original_settings = settings_path.read_bytes()
    original_bar = bar_path.read_bytes()
    settings = json.loads(original_settings.decode('utf-8-sig'))
    statusline = settings.get('statusLine', {})
    if not isinstance(statusline, dict) or statusline.get('type', 'command') != 'command':
        raise ValueError('Unsupported existing statusline configuration')
    delegate = statusline.get('command', '')
    if not isinstance(delegate, str):
        raise ValueError('Existing statusline command must be a string')
    cache = windows_home / 'AppData/Local/Winarchy/cache/claude-usage/snapshot.json'
    if cache.resolve().is_relative_to(config_home.resolve()):
        raise ValueError('The quota cache must be outside Winarchy configuration')
    new_bar = patched_bar(original_bar)
    command = shlex.join(['python3', str(runtime / 'bridge.py'), '--config', str(runtime / 'bridge.json')])
    settings['statusLine'] = dict(statusline, type='command', command=command)
    new_settings = (json.dumps(settings, indent=2, ensure_ascii=False) + '\n').encode()
    bridge_config = (json.dumps({'cache': str(cache), 'delegate': delegate}, indent=2) + '\n').encode()
    # Backups are private, outside Git and outside the watched Winarchy configuration.
    backup_root = local_home / '.local/state/winarchy-applet-collection/backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=backup_root))
    (backup / 'claude-settings.json').write_bytes(original_settings)
    (backup / 'bar.toml').write_bytes(original_bar)
    changed = []
    created = []
    try:
        runtime.mkdir(parents=True)
        created.append(runtime)
        shutil.copyfile(ROOT / 'claude-usage/bridge.py', runtime / 'bridge.py')
        (runtime / 'bridge.json').write_bytes(bridge_config)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.claude-install-', dir=target.parent) as stage:
            for name in FILES:
                shutil.copyfile(ROOT / 'claude-usage' / name, Path(stage) / name)
            # Publish a complete folder, before referencing it in bar.toml.
            os.rename(stage, target)
        created.append(target)
        if settings_path.read_bytes() != original_settings or bar_path.read_bytes() != original_bar:
            raise ValueError('Configuration changed concurrently; installation cancelled')
        for path, before, after in [(settings_path, original_settings, new_settings), (bar_path, original_bar, new_bar)]:
            if path.read_bytes() != before:
                raise ValueError('Configuration changed concurrently; installation cancelled')
            atomic_write(path, after)
            changed.append((path, before, after))
    except Exception:
        for path, before, after in reversed(changed):
            if path.read_bytes() == after:
                atomic_write(path, before)
        for path in reversed(created):
            shutil.rmtree(path)
        raise
    result = {'backup': str(backup), 'applet': str(target), 'relay': str(runtime), 'cache': str(cache)}
    (backup / 'installation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-home', type=Path, required=True, help='WSL-visible Windows profile, e.g. /mnt/c/Users/Name')
    parser.add_argument('--config-home', type=Path, help='WSL-visible WINARCHY_CONFIG_HOME override, if used')
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        result = install(args.windows_home, args.config_home or args.windows_home / '.config/winarchy', args.claude_home, Path.home())
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
