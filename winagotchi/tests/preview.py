#!/usr/bin/env python3
"""Fixture-only Slint renders. Run under a disposable Xvfb, never the desktop."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]


def fixture(form='child'):
    stage = form.split('_')[0]
    return dict(ready=True, generation=3, form=form, stage=stage,
                **{'form-label': 'a ' + form.replace('_', ' '), 'age': '8h 12m active',
                   'work-day': False, 'paused': False, 'care': 78, 'needs': [75, 65, 12, 80, 15], 'sleeping': False,
                   'mood': 'Hungry — time for a snack!', 'animation': 'idle', 'notice': ''})


def mouse(events):
    x = ctypes.CDLL('libX11.so.6'); t = ctypes.CDLL('libXtst.so.6')
    x.XOpenDisplay.restype = ctypes.c_void_p; x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XFlush.argtypes = [ctypes.c_void_p]; x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    t.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    t.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x.XOpenDisplay(None)
    assert display
    try:
        for event in events:
            if event[0] == 'move': t.XTestFakeMotionEvent(display, -1, event[1], event[2], 0)
            else: t.XTestFakeButtonEvent(display, 1, event[0] == 'down', 0)
            x.XFlush(display); time.sleep(.08)
    finally: x.XCloseDisplay(display)


def click(x, y):
    return [('move', x, y), ('down',), ('up',)]


def main():
    output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=True)
    scenes = [(form, {'data': fixture(form)}) for form in
              ['egg', 'baby', 'child', 'teen_neat', 'teen_scruffy', 'adult_ace', 'adult_ok', 'adult_gremlin']]
    scenes += [
        ('light', {'data': fixture(), 'bg': '#eff1f5', 'surface': '#e6e9ef', 'overlay': '#ccd0da', 'fg': '#4c4f69', 'muted': '#6c6f85', 'accent': '#8839ef'}),
        ('sleep-150', {'data': dict(fixture('adult_ace'), sleeping=True, animation='sleep', mood='Zzz…')}),
        ('small', {'data': dict(fixture(), notice='The egg hatched!'), 'popup-height': 400, 'popup-width': 340}),
        ('confirmation', {'data': fixture('adult_ace')}),
        ('error', {'data': fixture(), 'provider-error': 'Save is busy. Try again.'}),
        ('wash', {'data': fixture()}),
        ('work-day', {'data': dict(fixture(), **{'work-day': True, 'paused': True,
            'sleeping': True, 'animation': 'sleep', 'mood': 'Work day pause — back Mon–Fri, 09:00–18:00'})}),
        ('animated', {'data': fixture(), 'open': True}),
        ('scale-200', {'data': fixture('teen_scruffy')}),
    ]
    for name, values in scenes:
        with tempfile.TemporaryDirectory() as directory:
            fixture_file = Path(directory) / 'data.json'; fixture_file.write_text(json.dumps(values))
            action_log = Path(directory) / 'actions'
            recorder = Path(directory) / 'record.py'
            recorder.write_text('import sys\nwith open(sys.argv[1], "a") as f: f.write(sys.argv[2] + "\\n")\n')
            with (Path(directory) / 'errors').open('w+') as errors:
                p = subprocess.Popen(['slint-viewer', '--backend', 'winit-software', '--load-data', str(fixture_file),
                                      '--on', 'action', f'python3 {recorder} {action_log} "$1"', str(ROOT / 'view.slint')],
                                     stdout=subprocess.DEVNULL, stderr=errors,
                                     env=dict(os.environ, SLINT_SCALE_FACTOR='1.5' if name.endswith('-150') else '2' if name.endswith('-200') else '1'))
                try:
                    time.sleep(1.5)
                    errors.seek(0); text = errors.read()
                    assert p.poll() is None, text
                    assert not text.strip(), text
                    if name == 'wash': mouse(click(205, 485))
                    if name == 'confirmation': mouse(click(205, 619))
                    time.sleep(.2)
                    image = ImageGrab.grab(); image.save(output / f'{name}.png')
                    if name == 'animated':
                        frames = set()
                        for _ in range(6):
                            frames.add(ImageGrab.grab().crop((160, 130, 250, 220)).tobytes())
                            time.sleep(.2)
                        assert len(frames) >= 2, 'Visible pet must animate'
                    if name == 'child':
                        time.sleep(.6)
                        assert ImageGrab.grab().crop((160, 130, 250, 220)).tobytes() == image.crop((160, 130, 250, 220)).tobytes(), 'Closed popup must stop its animation'
                        pixels = list(image.crop((160, 130, 250, 220)).convert('RGB').getdata())
                        assert sum(r > 170 and g > 160 and b > 180 for r, g, b in pixels) > 150, 'Pixel pet must actually render'
                        mouse(click(205, 170)); time.sleep(1)
                        assert action_log.exists(), 'No pet action emitted'
                        assert action_log.read_text().splitlines() == ['pet'], 'Click must pet exactly once'
                        mouse(click(205, 170)); time.sleep(.2)
                        assert action_log.read_text().splitlines() == ['pet'], 'Pending action must block duplicate clicks'
                    if name == 'work-day':
                        mouse(click(205, 170) + click(75, 485)); time.sleep(.2)
                        assert not action_log.exists(), 'Paused care must not emit actions'
                        mouse(click(205, 529)); time.sleep(.3)
                        assert action_log.read_text().splitlines() == ['work-day off']
                    if name == 'wash':
                        mouse([('move', 195, 170), ('down',), ('move', 225, 175), ('move', 185, 170), ('move', 225, 175), ('up',)])
                        time.sleep(.3)
                        actions = action_log.read_text().splitlines()
                        assert len(actions) == 1 and actions[0].startswith('wash '), actions
                        assert 0 < float(actions[0][5:]) <= 25, actions
                    if name == 'confirmation':
                        # A click where the pet was must not pass through the modal.
                        mouse(click(205, 170)); time.sleep(.2)
                        assert not action_log.exists(), 'Confirmation must block the room'
                        mouse(click(205, 396)); time.sleep(.3)
                        assert action_log.read_text().splitlines() == ['farewell 3'], 'Goodbye must pin the displayed generation'
                finally:
                    if p.poll() is None: p.terminate()
                    p.wait(timeout=5)
    print(f'{len(scenes)} Slint fixtures and pet/scrub/modal interactions passed: {output}')


if __name__ == '__main__': main()
