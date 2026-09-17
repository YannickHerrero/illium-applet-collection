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


def session(name, display, state, summary, count, projects, agents, running=True):
    return {'name': name, 'display': display, 'running': running, 'is-default': name == 'default', 'agent-count': count,
            'summary-state': state, 'summary': summary, 'projects': projects, 'agents': agents}


sessions = [
    session('default', 'Shared session', 'working', '1 working', '2 agents', 'checkout-service  ·  design-tokens',
            [agent('Rewrite the receipt formatter', 'working'), agent('Token names for the new palette', 'idle')]),
    session('3', 'Workspace 3', 'blocked', '1 needs you', '1 agent', 'billing-api',
            [agent('Drop the legacy invoice table before the migration lands', 'blocked')]),
    session('5', 'Workspace 5', 'done', '2 done', '2 agents', 'docs-site',
            [agent('Upgrade the search index', 'done'), agent('Fix the broken anchor links', 'done')]),
    session('9', 'Workspace 9', 'stopped', 'stopped', '', 'nothing saved', [], running=False),
]
data = {'ok': True, 'error': '', 'bar-label': '!3', 'title': 'Herdr (3 servers, 5 agents)', 'sessions': sessions}
many = dict(data, title='Herdr (1 server, 14 agents)', sessions=[session('default', 'Shared session', 'idle', 'ready', '14 agents', 'winarchy',
            [agent(f'Long running task number {i} with a title that keeps going past the column', 'idle') for i in range(14)])])
light = {'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85', 'accent': '#8839ef'}
for name, values in [
    ('dark', {'data': data}),
    ('light', dict(light, data=data)),
    ('many', {'data': many}),
    ('empty', {'data': dict(data, title='Herdr (0 servers, 0 agents)', sessions=[])}),
    ('unreachable', {'data': {'ok': False, 'error': 'herdr is not installed in WSL', 'bar-label': '', 'title': 'Herdr', 'sessions': []}}),
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
