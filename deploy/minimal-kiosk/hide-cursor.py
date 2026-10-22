#!/usr/bin/python3
"""Hide the cursor for this X session; visibility is restored on disconnect."""
import ctypes as C
import signal
import time
x11=C.CDLL('libX11.so.6');fixes=C.CDLL('libXfixes.so.3')
x11.XOpenDisplay.argtypes=[C.c_char_p];x11.XOpenDisplay.restype=C.c_void_p
x11.XDefaultRootWindow.argtypes=[C.c_void_p];x11.XDefaultRootWindow.restype=C.c_ulong
x11.XFlush.argtypes=[C.c_void_p]
x11.XCloseDisplay.argtypes=[C.c_void_p]
fixes.XFixesHideCursor.argtypes=[C.c_void_p,C.c_ulong]
display=x11.XOpenDisplay(None)
if not display:raise SystemExit('Cannot open kiosk X display')
fixes.XFixesHideCursor(display,x11.XDefaultRootWindow(display));x11.XFlush(display)
def stop(*args):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
 while True:time.sleep(30)
finally:x11.XCloseDisplay(display)
