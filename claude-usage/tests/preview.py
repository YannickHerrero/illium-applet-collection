#!/usr/bin/env python3
"""Optional UI smoke test: xvfb-run -a python3 tests/preview.py /tmp/claude-preview.
Requires Slint viewer 1.12.1 and Pillow for development only. Never runs a provider.
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
quota = {"label": "Session · 5h", "value": 34, "used": "34%", "resets": "Resets in 4h 14m", "reset-time": "Mon 21:07", "pace": "19 pts ahead", "pace-value": 15, "fresh": True, "ahead": True}
data = {"message": "From active Claude Code sessions on WSL", "updated": "Last CLI update 16:53 · 0m ago", "error": "", "windows": [quota, dict(quota, label="Weekly", value=68, used="68%", resets="Resets in 2d 5h", pace="On linear pace", **{"pace-value":68, "ahead":False})]}
for name, values in [
    ("dark", {"data": data}),
    ("light", {"data": data, "bg":"#ffffff", "surface":"#f7f7f7", "overlay":"#e6e6e6", "fg":"#0a0a0a", "muted":"#565656", "accent":"#0a0a0a"}),
    ("waiting", {"data":dict(data, windows=[], message="Waiting for Claude Code usage data", updated="No quota snapshot yet")}),
    ("stale", {"data":dict(data, windows=[dict(quota, fresh=False, used="~34%", pace="Last known quota", resets="Window reset; awaiting update")], message="Session window reset; waiting for Claude Code")}),
]:
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / 'data.json'
        fixture.write_text(json.dumps(values, ensure_ascii=False))
        with (Path(directory) / 'errors').open('w+') as errors:
            process = subprocess.Popen(['slint-viewer', '--backend', 'winit-software', '--load-data', str(fixture), str(ROOT / 'view.slint')], stdout=subprocess.DEVNULL, stderr=errors)
            try:
                time.sleep(2)
                assert process.poll() is None, f'{name}: viewer exited'
                ImageGrab.grab().save(output / f'{name}.png')
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            text = errors.read()
            assert not text.strip(), text
print('Four Slint fixtures compiled and rendered:', output)
