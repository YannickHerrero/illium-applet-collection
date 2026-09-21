#!/usr/bin/env python3
"""Synthetic Slint smoke tests. Run under xvfb-run; never executes a calendar provider."""
import copy
import ctypes
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from PIL import ImageGrab

def click(xpos, ypos):
    x = ctypes.CDLL('libX11.so.6')
    t = ctypes.CDLL('libXtst.so.6')
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    t.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    t.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x.XOpenDisplay(None)
    assert display
    try:
        t.XTestFakeMotionEvent(display, -1, xpos, ypos, 0)
        for down in (1, 0):
            t.XTestFakeButtonEvent(display, 1, down, 0)
            x.XFlush(display)
            time.sleep(.08)
    finally:
        x.XCloseDisplay(display)
    time.sleep(.2)


ROOT = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
start = datetime.date(2026, 8, 31)
cells = []
for i in range(42):
    day = start + datetime.timedelta(days=i)
    cells.append(dict(day=day.day, date=day.isoformat(), current=day.month == 9, today=day.day == 12 and day.month == 9, selected=day.day == 12 and day.month == 9, count=2 if i % 3 == 0 else 0))
data = dict(month='September 2026', day='Saturday, September 12', weeks=[cells[i:i+7] for i in range(0, 42, 7)],
            calendars=[dict(key='a'*64, name='Calendar', connection='Outlook', visible=True, color=0), dict(key='b'*64, name='Personal · fixture only', connection='Second source', visible=True, color=2), dict(key='c'*64, name='Family', connection='Second source', visible=False, color=3)],
            events=[dict(key='d'*64, title='Weekly planning · Réunion', location='Room 201', time='09:00 - 10:00', calendar='Calendar', color=0, ongoing=True, join=True), dict(key='e'*64, title='A very long event title that should truncate without pushing the controls out of the popup', location='A very long room description / Building 4 / Floor 12', time='All day', calendar='Personal', color=2, ongoing=False, join=False)],
            statuses=[dict(name='Outlook', message='Read locally Sep 12 09:30', stale=False), dict(name='Second source', message='Synthetic fixture, not a Proton integration', stale=False)], more=0, empty=False)
empty = copy.deepcopy(data)
empty.update(events=[], empty=True)
for calendar in empty['calendars']:
    calendar['visible'] = False
for week in empty['weeks']:
    for cell in week:
        cell['count'] = 0
failed = copy.deepcopy(data)
failed['statuses'][1].update(message='Calendar unavailable. Using cached data.', stale=True)
light = dict(bg='#eff1f5', surface='#e6e9ef', overlay='#ccd0da', fg='#4c4f69', muted='#6c6f85', accent='#8839ef')
fixtures = [('dark', dict(data=data)), ('light', dict(light, data=data)), ('scale-150', dict(data=data)), ('empty', dict(data=empty)), ('busy', dict(data=data, busy=True)), ('failed-source', dict(data=failed)), ('initial-error', {'provider-error': 'Synthetic failure'})]
for name, values in fixtures:
    with tempfile.TemporaryDirectory() as temp:
        fixture = Path(temp) / 'fixture.json'
        fixture.write_text(json.dumps(values, ensure_ascii=False))
        action_log = Path(temp) / 'actions'
        recorder = Path(temp) / 'record.py'
        recorder.write_text('import sys\nwith open(sys.argv[1], "a") as f: f.write(sys.argv[2] + "\\n")\n')
        with (Path(temp) / 'errors').open('w+') as errors:
            process = subprocess.Popen(['slint-viewer', '--backend', 'winit-software', '--load-data', str(fixture), '--on', 'action', f'python3 {recorder} {action_log} "$1"', str(ROOT / 'view.slint')], stdout=subprocess.DEVNULL, stderr=errors, env=dict(os.environ, SLINT_SCALE_FACTOR='1.5' if name == 'scale-150' else '1'))
            try:
                for _ in range(20):
                    time.sleep(0.3)
                    if process.poll() is not None:
                        errors.seek(0)
                        raise AssertionError(errors.read())
                    image = ImageGrab.grab()
                    if image.crop((0, 0, 480, 780)).getextrema() != ((0, 0), (0, 0), (0, 0)):
                        break
                else:
                    raise AssertionError(f'{name}: no frame rendered')
                image.save(output / (name + '.png'))
                if name in ('dark', 'busy'):
                    for point in [(25, 433), (392, 75), (367, 180), (75, 619)]:
                        click(*point)
                    if name == 'busy':
                        assert not action_log.exists(), 'Busy controls must not queue duplicate actions'
                    else:
                        assert action_log.read_text().splitlines() == ['toggle ' + 'b'*64, 'month 1', 'day 2026-09-12', 'join ' + 'd'*64]
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            assert not errors.read().strip(), 'Unexpected Slint warnings'
print(f'{len(fixtures)} synthetic Slint fixtures rendered: {output}')
