#!/usr/bin/env python3
"""Opt-in read-only Windows Outlook smoke test. No installation, private output or links opened."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--windows-home', required=True, type=Path)
args = parser.parse_args()
base = args.windows_home / 'AppData/Local/Temp'
folder = Path(tempfile.mkdtemp(prefix='illium-agenda-test-', dir=base))
try:
    for source in ROOT.rglob('*.ps1'):
        destination = folder / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding='utf-8-sig'), encoding='utf-8-sig')
    windows = subprocess.check_output(['wslpath', '-w', str(folder)], text=True).strip().replace("'", "''")

    def invoke(action=''):
        assert "'" not in action
        command = f"$env:LOCALAPPDATA='{windows}'; & '{windows}\\agenda.ps1' '{action}'"
        start = time.monotonic()
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command], capture_output=True, timeout=24)
        assert result.returncode == 0, 'Provider failed (private output suppressed)'
        data = json.loads(result.stdout.decode('utf-8-sig'))
        assert len(result.stdout) < 65536
        print(json.dumps({'action': action.split(' ')[0] or 'read', 'seconds': round(time.monotonic() - start, 2), 'calendars': len(data['calendars']), 'day_events': len(data['events']), 'stale_sources': sum(s['stale'] for s in data['statuses'])}))
        return data

    first = invoke()
    if not first['calendars']:
        first = invoke('refresh')  # Cold Outlook startup may exceed the initial worker budget.
    assert first['calendars'] and not any(s['stale'] for s in first['statuses']), 'Outlook did not become available; check its profile/prompts'
    cached = invoke()
    assert [c['key'] for c in cached['calendars']] == [c['key'] for c in first['calendars']]
    for calendar in cached['calendars']:
        hidden = invoke('toggle ' + calendar['key'])
    assert not hidden['events']
    assert all(cell['count'] == 0 for week in hidden['weeks'] for cell in week)
    again = invoke()
    assert all(not c['visible'] for c in again['calendars']), 'Visibility must persist'
    for calendar in cached['calendars']:
        invoke('toggle ' + calendar['key'])
    invoke('month 1')
    invoke('today')
    # Unknown provider proves one failed connection cannot discard the healthy source.
    config_path = folder / 'Illium/calendar-agenda/connections.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    config['connections'].append({'id': 'unavailable-test', 'name': 'Unavailable test', 'provider': 'unsupported', 'enabled': True})
    config_path.write_text(json.dumps(config), encoding='utf-8')
    partial = invoke()
    assert len(partial['calendars']) == len(first['calendars'])
    assert len(partial['statuses']) == 2 and partial['statuses'][1]['stale']
    print('Live Outlook checks passed; no event contents displayed or modified.')
finally:
    shutil.rmtree(folder)
