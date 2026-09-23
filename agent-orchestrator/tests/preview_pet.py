#!/usr/bin/env python3
"""Render the actual Winarchy bar with all pet states, without running providers.

xvfb-run -a python3 -B tests/preview_pet.py /tmp/pet-preview --shell-ui /path/to/winarchy/ui/shell.slint
Requires Slint viewer 1.12.1 and Pillow (development only).
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import tomllib
from PIL import ImageGrab, ImageChops

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('--shell-ui', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
pack = tomllib.loads((ROOT / 'glitchcat.toml').read_text())
items = []
for state, animation in pack['states'].items():
    fields = ', '.join(f'{key.replace("_", "-")}: {pack[key]}' for key in
                       ('frame_width', 'frame_height', 'interval_ms', 'display_height'))
    items.append('{kind: ' + json.dumps(state) + ', value: ' + json.dumps(state) + ', sprite: {'
                 + 'sheet: @image-url(' + json.dumps(str(ROOT / pack['sheet'])) + '), '
                 + fields + f', row: {animation["row"]}, frames: {animation["frames"]}' + '}}')
source = ('import { Bar } from ' + json.dumps(str(args.shell_ui.resolve())) + ';\n'
          'export component Preview inherits Bar { surface-width: 640px; surface-height: 40px; '
          'bg: #1e1e2e; fg: #cdd6f4; muted: #a6adc8; accent: #89b4fa; '
          'center-items: [' + ','.join(items) + ']; }')
for scale in ('1', '1.5', '2'):
    with tempfile.TemporaryDirectory() as directory:
        view = Path(directory) / 'preview.slint'
        view.write_text(source)
        with (Path(directory) / 'errors').open('w+') as errors:
            process = subprocess.Popen(['slint-viewer', '--backend', 'winit-software', str(view)],
                                       env=dict(os.environ, SLINT_SCALE_FACTOR=scale),
                                       stdout=subprocess.DEVNULL, stderr=errors)
            try:
                time.sleep(3)
                assert process.poll() is None, 'viewer exited'
                frames = []
                for _ in range(10):
                    frames.append(ImageGrab.grab().crop((0, 0, round(640 * float(scale)), round(40 * float(scale)))))
                    time.sleep(0.15)
                assert any(ImageChops.difference(frames[0], frame).getbbox() for frame in frames[1:]), 'sprite is not animating'
                frames[0].save(args.output / f'pet-{scale}x.png')
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            assert not errors.read().strip(), 'Slint emitted diagnostics'
print('Five pet states rendered and animated at 1x, 1.5x and 2x:', args.output)
