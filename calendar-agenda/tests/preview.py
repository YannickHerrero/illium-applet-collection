#!/usr/bin/env python3
"""Synthetic graphical regression checks under Xvfb; never runs Outlook or opens links.
Optionally set CALENDAR_AGENDA_FONT_DIR to a directory containing JetBrainsMono NFM.
"""
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
from xml.sax.saxutils import escape
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


def window_geometry(expected_width):
    """Inspect the native X11 window, not merely the painted content rectangle."""
    x = ctypes.CDLL('libX11.so.6')
    handle = ctypes.c_void_p
    ulong = ctypes.c_ulong
    uint = ctypes.c_uint
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XOpenDisplay.restype = handle
    x.XDefaultRootWindow.argtypes = [handle]
    x.XDefaultRootWindow.restype = ulong
    x.XQueryTree.argtypes = [handle, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong), ctypes.POINTER(ctypes.POINTER(ulong)), ctypes.POINTER(uint)]
    x.XGetGeometry.argtypes = [handle, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(uint), ctypes.POINTER(uint), ctypes.POINTER(uint), ctypes.POINTER(uint)]
    x.XFree.argtypes = [handle]
    x.XCloseDisplay.argtypes = [handle]
    display = x.XOpenDisplay(None)
    assert display
    children = ctypes.POINTER(ulong)()
    try:
        root, parent, count = ulong(), ulong(), uint()
        assert x.XQueryTree(display, x.XDefaultRootWindow(display), ctypes.byref(root), ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count))
        matches = []
        for i in range(count.value):
            xpos, ypos = ctypes.c_int(), ctypes.c_int()
            width, height, border, depth = uint(), uint(), uint(), uint()
            if x.XGetGeometry(display, children[i], ctypes.byref(root), ctypes.byref(xpos), ctypes.byref(ypos), ctypes.byref(width), ctypes.byref(height), ctypes.byref(border), ctypes.byref(depth)) and width.value == expected_width:
                matches.append((xpos.value, ypos.value, width.value, height.value))
        assert len(matches) == 1, matches
        return matches[0]
    finally:
        if children:
            x.XFree(children)
        x.XCloseDisplay(display)


ROOT = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
start = datetime.date(2026, 8, 30)
cells = []
for i in range(42):
    day = start + datetime.timedelta(days=i)
    markers = [0, 2, 0][:1 + i % 3]
    cells.append(dict(day=day.day, date=day.isoformat(), current=day.month == 9,
                      today=day == datetime.date(2026, 9, 12), selected=day == datetime.date(2026, 9, 10), count=len(markers), markers=markers))


def event(index, title, time_label, location='', join=False, color=0):
    return dict(key=str(index)*64, title=title, location=location, time=time_label, calendar='Lab' if color == 0 else 'Personal', color=color, ongoing=False, join=join)


data = dict(**{'today-header': 'September 12', 'current-year': 2026, 'year-progress': 69.73, 'notice': '',
               'day-short': 'THU, SEP 10', 'day-count': 9, 'all-visible': True, 'week-numbers': list(range(36, 42))},
            month='SEPTEMBER 2026', day='Thursday, September 10', weeks=[cells[i:i+7] for i in range(0, 42, 7)],
            calendars=[dict(key='a'*64, name='Personal', label='Personal', connection='Outlook', visible=True, color=2),
                       dict(key='b'*64, name='Lab', label='Lab', connection='Outlook', visible=True, color=0)],
            events=[event(1, 'Annual leave', 'ALL DAY'), event(2, 'Research workshop', '08:00 - 09:00'),
                    event(3, 'Actuation and sensing design', '11:00 - 12:15', '302-619', color=2),
                    event(4, 'Quadruped', '11:00 - 12:00'), event(5, 'Project review', '13:00 - 14:00'),
                    event(6, 'Robotics project meeting', '14:00 - 15:00', join=True),
                    event(7, 'Linear Algebra', '15:30 - 16:45', color=2),
                    event(8, 'Topics in control and optimization', '17:00 - 18:15', '301-316', color=2),
                    event(9, 'Evening language class', '19:00 - 21:00', '38-418', color=2)], more=0, empty=False)
controls = copy.deepcopy(data)
controls['events'] = [event(1, 'Weekly planning · Réunion 日本語', '09:00 - 10:00', 'Room 201', join=True),
                      event(2, 'Long title that should truncate without displacing any controls', 'ALL DAY')]
controls['day-count'] = 2
empty = copy.deepcopy(data)
empty.update(events=[], empty=True, **{'day-count': 0, 'all-visible': False})
for calendar in empty['calendars']:
    calendar['visible'] = False
for week in empty['weeks']:
    for cell in week:
        cell.update(count=0, markers=[])
failed = copy.deepcopy(data)
failed['notice'] = 'Second source: Calendar unavailable. Using cached data.'
light = dict(bg='#eff1f5', surface='#e6e9ef', overlay='#ccd0da', fg='#4c4f69', muted='#6c6f85', accent='#8839ef')
akane = dict(bg='#12101c', surface='#221c2c', overlay='#2c2438', fg='#f0c4a8', muted='#8a6e6c', accent='#e15a48')
many = copy.deepcopy(controls)
many['events'] = [event(i % 9 + 1, f'Meeting {i + 1}', '09:00 - 10:00', 'Room 201', join=True) for i in range(30)]
many['day-count'] = 30
sizes = {}
fixtures = [('dark', dict(data=data)), ('light', dict(light, data=data)), ('akane', dict(akane, data=data)),
            ('akane-125', dict(akane, data=data)), ('scale-150', dict(data=data)), ('empty', dict(data=empty)),
            ('controls', dict(data=controls)), ('busy', dict(data=controls, busy=True)),
            ('failed-source', dict(data=failed)), ('initial-error', {'provider-error': 'Synthetic failure'}),
            ('opened', dict(data=controls, open=True)), ('many', dict(data=many)),
            ('lower-cap', dict(data=many, **{'popup-height': 620}))]
for name, values in fixtures:
    values = copy.deepcopy(values)
    if 'data' in values:
        snapshot = values['data']
        snapshot['days'] = [dict(date=(start + datetime.timedelta(days=i)).isoformat(),
                                 label=(start + datetime.timedelta(days=i)).strftime('%a, %b %d').upper(),
                                 count=snapshot['day-count'], events=copy.deepcopy(snapshot['events']), more=snapshot['more'])
                            for i in range(42)]
        snapshot['day-index'] = 11
        snapshot['today-index'] = 13
        for old in ('day', 'day-short', 'day-count', 'events', 'more', 'empty'):
            snapshot.pop(old, None)
    with tempfile.TemporaryDirectory() as temp:
        fixture = Path(temp) / 'fixture.json'
        fixture.write_text(json.dumps(values, ensure_ascii=False))
        action_log = Path(temp) / 'actions'
        recorder = Path(temp) / 'record.py'
        recorder.write_text('import sys\nwith open(sys.argv[1], "a") as f: f.write(sys.argv[2] + "\\n")\n')
        scale = 1.5 if name == 'scale-150' else 1.25 if name == 'akane-125' else 1
        env = dict(os.environ, SLINT_SCALE_FACTOR=str(scale))
        if os.environ.get('CALENDAR_AGENDA_FONT_DIR'):
            config = Path(temp) / 'fonts.conf'
            config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                              '<include>/etc/fonts/fonts.conf</include><dir>' + escape(os.environ['CALENDAR_AGENDA_FONT_DIR']) + '</dir></fontconfig>')
            env['FONTCONFIG_FILE'] = str(config)
        with (Path(temp) / 'errors').open('w+') as errors:
            process = subprocess.Popen(['slint-viewer', '--backend', 'winit-software', '--load-data', str(fixture), '--on', 'action', f'python3 {recorder} {action_log} "$1"', str(ROOT / 'view.slint')], stdout=subprocess.DEVNULL, stderr=errors, env=env)
            try:
                for _ in range(30):
                    time.sleep(0.3)
                    if process.poll() is not None:
                        errors.seek(0)
                        raise AssertionError(errors.read())
                    image = ImageGrab.grab().crop((0, 0, round(440*scale), round(820*scale)))
                    if image.getextrema() != ((0, 0), (0, 0), (0, 0)):
                        break
                else:
                    raise AssertionError(f'{name}: no frame rendered')
                # Let conditional repeaters and font loading finish before inspecting pixels.
                time.sleep(.7)
                xpos, ypos, width, height = window_geometry(round(440*scale))
                sizes[name] = height / scale
                assert height <= round(values.get('popup-height', 820) * scale), f'{name}: exceeded maximum height'
                image = ImageGrab.grab().crop((xpos, ypos, xpos + width, ypos + height))
                image.save(output / (name + '.png'))
                if name == 'opened':
                    assert action_log.read_text().splitlines() == [''], 'Opening refreshes only once'
                if name in ('dark', 'light', 'akane', 'akane-125', 'scale-150'):
                    # Nine cards fit without scrolling. Numeric locations must not be
                    # clipped by fractional text metrics at 125% Windows scaling.
                    for region in [(58, 507, 180, 521), (58, 754, 250, 768)]:
                        crop = image.crop(tuple(round(v * scale) for v in region))
                        assert len(crop.getcolors() or []) > 4, f'{name}: missing location or ninth event text'
                if name in ('controls', 'busy'):
                    for point in [(168, 386), (382, 324), (368, 175), (100, 459), (380, 360), (64, 386), (342, 360)]:
                        click(*point)
                    if name == 'busy':
                        assert not action_log.exists(), 'Busy controls must not queue duplicate actions'
                    else:
                        actions = action_log.read_text().splitlines() if action_log.exists() else []
                        assert actions == ['toggle ' + 'b'*64, 'month 1', 'join ' + '1'*64, 'refresh', 'show-all'], actions
            finally:
                process.terminate()
                process.wait(timeout=5)
            errors.seek(0)
            assert not errors.read().strip(), 'Unexpected Slint warnings'
assert sizes['empty'] == sizes['controls'] == sizes['dark'] == 820, sizes
assert sizes['opened'] == sizes['controls'], 'Opening must not change geometry'
assert sizes['many'] == 820 and sizes['lower-cap'] == 620, sizes
print(f'{len(fixtures)} Slint fixtures, native size limits and interactions passed: {output}')
