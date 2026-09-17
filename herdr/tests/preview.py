#!/usr/bin/env python3
"""Optional UI smoke test: xvfb-run -a python3 tests/preview.py /tmp/herdr-preview.
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


def agent(title, status):
    label = {'blocked': 'needs you', 'idle': 'ready'}.get(status, status)
    return {'title': title, 'status': status, 'label': label}


def card(title, subtitle, state, summary, count, agents, active=True):
    return {'title': title, 'subtitle': subtitle, 'attention': state, 'summary': summary, 'agent-count': count, 'active': active, 'agents': agents}


cards = [
    card('checkout-service', 'Workspace 1  ·  2 tabs', 'working', '1 working', '2 agents',
         [agent('Rewrite the receipt formatter', 'working'), agent('Token names for the new palette', 'idle')]),
    card('billing-api', 'Workspace 2  ·  1 tab', 'blocked', '1 needs you', '1 agent',
         [agent('Drop the legacy invoice table before the migration lands', 'blocked')]),
    card('docs-site', 'Workspace 3  ·  1 tab', 'done', '2 done', '2 agents',
         [agent('Upgrade the search index', 'done'), agent('Fix the broken anchor links', 'done')]),
    card('scratch', 'Workspace 4  ·  1 tab', 'empty', 'no agents', '', []),
    card('Workspace 9', 'nothing saved', 'stopped', 'stopped', '', [], active=False),
]
data = {'ok': True, 'error': '', 'bar-label': '!1', 'title': 'Herdr (1 server, 5 agents)', 'cards': cards}
many = dict(data, title='Herdr (1 server, 14 agents)', cards=[card('winarchy', 'Workspace 1  ·  6 tabs', 'idle', 'ready', '14 agents',
            [agent(f'Long running task number {i} with a title that keeps going past the column', 'idle') for i in range(14)])])
light = {'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85', 'accent': '#8839ef'}
for name, values in [
    ('dark', {'data': data}),
    ('light', dict(light, data=data)),
    ('many', {'data': many}),
    ('empty', {'data': dict(data, title='Herdr (0 servers, 0 agents)', cards=[])}),
    ('unreachable', {'data': {'ok': False, 'error': 'herdr is not installed in WSL', 'bar-label': '', 'title': 'Herdr', 'cards': []}}),
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
                    if image.crop((0, 0, 430, 560)).getextrema() != ((0, 0), (0, 0), (0, 0)):
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
