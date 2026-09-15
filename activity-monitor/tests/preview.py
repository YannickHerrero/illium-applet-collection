#!/usr/bin/env python3
"""Render fixture data only; never launches the provider or terminates anything."""
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
output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=True)


def select_and_ask():
    # Only used in our disposable Xvfb display; no real provider is connected.
    x=ctypes.CDLL('libX11.so.6');t=ctypes.CDLL('libXtst.so.6')
    x.XOpenDisplay.restype=ctypes.c_void_p;x.XOpenDisplay.argtypes=[ctypes.c_char_p]
    x.XFlush.argtypes=[ctypes.c_void_p];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
    x.XDefaultRootWindow.argtypes=[ctypes.c_void_p];x.XDefaultRootWindow.restype=ctypes.c_ulong
    x.XQueryPointer.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_ulong)]+[ctypes.POINTER(ctypes.c_int)]*4+[ctypes.POINTER(ctypes.c_uint)]
    x.XSetInputFocus.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
    x.XStringToKeysym.argtypes=[ctypes.c_char_p];x.XStringToKeysym.restype=ctypes.c_ulong
    x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XKeysymToKeycode.restype=ctypes.c_uint
    t.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
    t.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
    t.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
    display=x.XOpenDisplay(None)
    assert display
    try:
        t.XTestFakeMotionEvent(display,-1,80,224,0)
        t.XTestFakeButtonEvent(display,1,1,0);t.XTestFakeButtonEvent(display,1,0,0);x.XFlush(display)
        time.sleep(.2)
        parent=ctypes.c_ulong();child=ctypes.c_ulong();coords=[ctypes.c_int() for _ in range(4)];mask=ctypes.c_uint()
        x.XQueryPointer(display,x.XDefaultRootWindow(display),ctypes.byref(parent),ctypes.byref(child),*[ctypes.byref(v) for v in coords],ctypes.byref(mask))
        assert child.value
        x.XSetInputFocus(display,child.value,1,0);x.XFlush(display)
        time.sleep(.1)
        key=x.XKeysymToKeycode(display,x.XStringToKeysym(b'x'))
        t.XTestFakeKeyEvent(display,key,1,0);t.XTestFakeKeyEvent(display,key,0,0);x.XFlush(display)
        time.sleep(.3)
    finally:x.XCloseDisplay(display)

processes = [dict(key=f'{i}:12345', pid=str(i), name=name, cpu='12.3%', memory='1.4 GiB', **{'can-end': True}) for i, name in enumerate(['firefox.exe', 'vmmemWSL', 'Éditeur 日本語.exe'] + [f'worker-{i}.exe' for i in range(77)], 100)]
data = {'cpu':'12%', 'ram':'38%', 'ram-detail':'12.2 GiB / 32 GiB · 19.8 GiB available', 'uptime':'Uptime 1d 4h 25m',
        'cpu-chart':[dict(x1=i*10,x2=(i+1)*10,y1=y,y2=z) for i,(y,z) in enumerate(zip([12,20,8,10,27,20,12,50,15,12],[20,8,10,27,20,12,50,15,12,12]))],
        'ram-chart':[dict(x1=i*20,x2=(i+1)*20,y1=y,y2=z) for i,(y,z) in enumerate(zip([28,29,40,38,39],[29,40,38,39,38]))],
        'network-name':'Wi-Fi', 'down':'963 KiB/s', 'up':'5.0 KiB/s', 'disk-name':'Physical disk 0', 'disk-read':'2.0 MiB/s', 'disk-write':'340 KiB/s',
        'volumes':[dict(name='C:',detail='180 GiB free / 512 GiB',used=65)], 'processes':processes, 'busiest':processes[:3],
        'process-summary':'80 of 291 matches · 291 processes sampled', 'status':'Live · 60s history', 'notice':'', 'selected-key':'', 'selected-index':-1}
for name, values in [
    ('overview-dark', {'data':data}),
    ('overview-light', {'data':data,'bg':'#ffffff','surface':'#f7f7f7','overlay':'#e6e6e6','fg':'#0a0a0a','muted':'#565656','accent':'#0a0a0a'}),
    ('processes', {'data':data,'tab':1}),
    ('processes-150', {'data':data,'tab':1}),
    ('confirmation', {'data':data,'tab':1,'confirming':True}),
    ('unavailable', {'data':dict(data, cpu='—', processes=[], volumes=[], **{'cpu-chart':[],'process-summary':'Process enumeration unavailable'}),'tab':1}),
    ('small', {'data':data,'popup-height':480,'popup-width':480}),
]:
    with tempfile.TemporaryDirectory() as directory:
        fixture=Path(directory)/'data.json';fixture.write_text(json.dumps(values,ensure_ascii=False))
        with (Path(directory)/'errors').open('w+') as errors:
            p=subprocess.Popen(['slint-viewer','--backend','winit-software','--load-data',str(fixture),str(ROOT/'view.slint')],stdout=subprocess.DEVNULL,stderr=errors,env=dict(os.environ,SLINT_SCALE_FACTOR='1.5' if name.endswith('-150') else '1'))
            try:
                time.sleep(2)
                errors.seek(0);text=errors.read()
                assert p.poll() is None, text
                assert not text.strip(),text
                image=ImageGrab.grab();image.save(output/f'{name}.png')
                if name=='overview-dark':
                    pixels=list(image.crop((30,195,256,230)).convert('RGB').getdata())
                    assert sum(r>150 and b>r and g<r for r,g,b in pixels)>40, 'CPU graph must actually draw in SoftwareRenderer'
                if name=='processes':
                    select_and_ask()
                    confirmation=ImageGrab.grab();confirmation.save(output/'selected-confirmation.png')
                    pixels=list(confirmation.crop((16,15,300,60)).convert('RGB').getdata())
                    assert sum(max(p)>140 for p in pixels)<10, 'x must open a modal covering the old header, not just select a row'
                    assert p.poll() is None, 'Interaction must not crash the view' 
            finally:
                if p.poll() is None:p.terminate()
                p.wait(timeout=5)
print('Seven Slint fixtures plus selection/confirmation interaction rendered:',output)
