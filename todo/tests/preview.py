#!/usr/bin/env python3
"""Optional UI smoke test: xvfb-run -a python3 tests/preview.py /tmp/todo-preview.
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


def task(identifier, text, done=False):
    return {'id': str(identifier), 'text': text, 'done': done}


def payload(tasks, error=''):
    remaining = sum(1 for t in tasks if not t['done'])
    done = len(tasks) - remaining
    headline = 'nothing planned' if not tasks else 'all done' if not remaining else f'{remaining} remaining'
    return {
        'bar-label': str(remaining) if remaining else '',
        'headline': headline,
        'remaining': remaining,
        'done': done,
        'tasks': tasks,
        'error': error,
    }


mixed = [
    task(1, 'Hello from Omado'),
    task(2, 'Complete Creational patterns', True),
    task(3, 'Écrire la rétrospective de sprint', True),
]
light = {'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85', 'accent': '#8839ef', 'red': '#d20f39'}
long_list = [task(i, f'Task number {i} with a title that runs well past the column width', i % 3 == 0) for i in range(1, 15)]
for name, values in [
    ('dark', {'data': payload(mixed)}),
    ('light', dict(light, data=payload(mixed))),
    ('empty', {'data': payload([])}),
    ('long', {'data': payload(long_list)}),
    ('error', {'data': payload(mixed, 'Task file unreadable: C:\\Users\\Someone\\tasks.json')}),
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
                    if image.crop((0, 0, 360, 440)).getextrema() != ((0, 0), (0, 0), (0, 0)):
                        break
                else:
                    raise AssertionError(f'{name}: nothing rendered')
                image.save(output / f'{name}.png')
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            text = errors.read()
            assert not text.strip(), text
print('Five Slint fixtures compiled and rendered:', output)
