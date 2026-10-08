#!/usr/bin/env python3
"""Optional UI smoke test: xvfb-run -a python3 tests/preview.py /tmp/solaris-preview.
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


def producer(identifier, name, owned, rate, cost, scaled):
    return {'id': str(identifier), 'name': name, 'owned': str(owned), 'rate': rate, 'cost-1': cost,
            'cost-10': '42.40M', 'cost-max': '8.21M', 'max': '7' if scaled <= 12.34 else '0',
            'cost-1-scaled': scaled, 'cost-10-scaled': 42.4}


game = {
    'in-terminal': False, 'bar-label': '12.34M', 'energy-scaled': 12.34, 'unit': 'M',
    'eps-scaled': 0.0456, 'click-scaled': 0.0023, 'eps': '45.60K/s', 'click': '2.28K',
    'producers': [
        producer(1, 'Solar Panel', 120, '1.20K/s', '2.31M', 2.31),
        producer(2, 'Mining Drone', 85, '9.80K/s', '4.02M', 4.02),
        producer(3, 'Asteroid Mine', 42, '14.10K/s', '9.95M', 9.95),
        producer(4, 'Orbital Station', 12, '20.50K/s', '15.20M', 15.2),
    ] + [producer(i, f'Producer {i}', 0, '0.0/s', '1.00B', 1000.0) for i in range(5, 12)],
    'upgrades': [
        {'id': '7', 'name': 'Reinforced Panels', 'description': 'Solar Panels are twice as efficient', 'cost': '5.00M', 'cost-scaled': 5.0},
        {'id': '31', 'name': 'Swarm Logic', 'description': 'Mining Drones gain +1% for every other building owned, which is a long description', 'cost': '50.00M', 'cost-scaled': 50.0},
    ],
    'upgrades-available': 2, 'achievements': '18/260', 'achievement': 'Novice Solar Panel',
    'chips': '3', 'ascension-chips': '1',
}
light = {'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85',
         'accent': '#8839ef', 'yellow': '#df8e1d', 'red': '#d20f39'}
for name, values in [
    ('producers', {'has-data': True, 'data': game}),
    ('upgrades', dict(light, **{'has-data': True, 'tab': 'upgrades', 'amount': 'max', 'data': dict(game, achievement='')})),
    ('max', {'has-data': True, 'amount': 'max', 'data': game}),
    ('terminal', {'has-data': True, 'data': {'in-terminal': True}}),
    ('loading', {}),
    ('error', {'provider-error': 'Save main.json: expected value at line 1 column 1'}),
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
                    if image.crop((0, 0, 420, 620)).getextrema() != ((0, 0), (0, 0), (0, 0)):
                        break
                else:
                    raise AssertionError(f'{name}: nothing rendered')
                image.crop((0, 0, 420, 620)).save(output / f'{name}.png')
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            text = errors.read()
            assert not text.strip(), text
print('Six Slint fixtures compiled and rendered:', output)
