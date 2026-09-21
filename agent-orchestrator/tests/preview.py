#!/usr/bin/env python3
"""Optional UI smoke test: xvfb-run -a python3 tests/preview.py /tmp/agent-orchestrator-preview.
Requires Slint viewer 1.12.1 and Pillow for development only. Never runs the collector.
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
WORDS = {'waiting': 'needs you', 'working': 'working', 'done': 'done', 'idle': 'ready'}


def card(source, agent, title, detail, status, place=''):
    return {'source': source, 'agent': agent, 'title': title, 'detail': detail, 'place': place, 'status': status, 'label': WORDS[status]}


cards = [
    card('herdr', 'Claude', 'Drop the legacy invoice table before the migration lands', '~/dev/billing-api', 'waiting', 'billing-api'),
    card('multica', 'Yuqi', 'DEV-102  Plan for the loyalty export', 'comment  ·  started 4 min', 'working'),
    card('herdr', 'Pi', 'Rewrite the receipt formatter', '~/dev/checkout-service', 'working', 'checkout-service'),
    card('multica', 'Minnie', 'DEV-101  Review the expert accountant role', 'direct  ·  started 12 min', 'working'),
    card('herdr', 'Claude', 'Upgrade the search index', '~/dev/docs-site', 'done', 'docs-site'),
    card('herdr', 'Codex', 'Token names for the new palette', '~/dev/winarchy', 'idle', 'winarchy'),
    card('herdr', 'Claude', 'Fix the broken anchor links', '~/dev/docs-site', 'idle', 'docs-site'),
]
summary = {'total': 7, 'waiting': 1, 'working': 3, 'done': 1, 'idle': 2, 'headline': '1 agent needs you'}
sources = [{'name': 'Herdr', 'state': 'ok', 'detail': '5 agents'}, {'name': 'Multica', 'state': 'ok', 'detail': '2 working'}]
data = {'ok': True, 'error': '', 'bar-label': '1', 'icon': 'icon-attention.svg', 'summary': summary, 'sources': sources, 'cards': cards}
light = {'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85', 'accent': '#8839ef'}
off = {'ok': True, 'error': '', 'bar-label': '', 'icon': 'icon.svg', 'summary': dict(summary, total=0, waiting=0, working=0, done=0, idle=0, headline='No source reachable'),
       'sources': [{'name': 'Herdr', 'state': 'off', 'detail': 'not running'}, {'name': 'Multica', 'state': 'error', 'detail': 'server unreachable'}], 'cards': []}
for name, values in [
    ('dark', {'data': data}),
    ('light', dict(light, data=data)),
    ('filtered', {'data': data, 'filter': 'waiting'}),
    ('off', {'data': off}),
    ('failed', {'data': {'ok': False, 'error': 'ValueError: boom', 'bar-label': '', 'icon': 'icon.svg', 'summary': summary, 'sources': [], 'cards': []}}),
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
                    if image.crop((0, 0, 460, 600)).getextrema() != ((0, 0), (0, 0), (0, 0)):
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
