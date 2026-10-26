#!/usr/bin/env python3
"""Optional UI smoke test: xvfb-run -a python3 tests/preview.py /tmp/time-tracker-preview.
Requires Slint viewer 1.12.1 and Pillow for development only. Never runs the provider.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)


def payload(working, today, week, error=''):
    return {
        'icon': 'icon-on.svg' if working else 'icon.svg',
        'bar-label': '',
        'working': working,
        'since': '09:30' if working else '',
        'weekday': True,
        'clocks': [
            {'name': 'Tokyo', 'second-of-day': 14 * 3600 + 7 * 60, 'date': 'Mon 26 Oct'},
            {'name': 'Paris', 'second-of-day': 6 * 3600 + 7 * 60, 'date': 'Mon 26 Oct'},
        ],
        'today-seconds': today,
        'week-seconds': week,
        'error': error,
    }


light = {'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85', 'accent': '#8839ef', 'green': '#40a02b', 'red': '#d20f39'}
for name, values in [
    ('working', {'data': payload(True, 3 * 3600 + 15 * 60, 19 * 3600 + 4 * 60)}),
    ('off', {'data': payload(False, 0, 0)}),
    ('light', dict(light, data=payload(True, 59, 7 * 3600))),
    ('error', {'data': payload(False, 3600, 3600, 'Session file unreadable: C:\\Users\\Someone\\sessions.json')}),
    # The click answered before the provider: off on the data, on on screen.
    ('starting', {'data': payload(False, 0, 0), 'intent': True, 'outstanding': 1}),
]:
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / 'data.json'
        fixture.write_text(json.dumps(values, ensure_ascii=False))
        with (Path(directory) / 'errors').open('w+') as errors:
            process = subprocess.Popen(['slint-viewer', '--backend', 'winit-software', '--load-data', str(fixture), str(ROOT / 'view.slint')], stdout=subprocess.DEVNULL, stderr=errors)
            try:
                # The software backend takes a moment to paint its first frame.
                for _ in range(20):
                    time.sleep(0.5)
                    assert process.poll() is None, f'{name}: viewer exited'
                    image = ImageGrab.grab()
                    if image.crop((0, 0, 360, 300)).getextrema() != ((0, 0), (0, 0), (0, 0)):
                        break
                else:
                    raise AssertionError(f'{name}: nothing rendered')
                image.crop((0, 0, 360, 300)).save(output / f'{name}.png')
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            text = errors.read()
            assert not text.strip(), text
print('Five Slint fixtures compiled and rendered:', output)
