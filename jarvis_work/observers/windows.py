"""Windows eyes.

Notably simpler than the macOS original this borrows from: the foreground
window and its title come from plain Win32 calls with no permission grant,
where macOS needs Screen Recording before it will hand over a window title
at all.

Every function used here has its `argtypes`/`restype` declared. ctypes defaults
an undeclared return to a *signed 32-bit int*, which silently truncates 64-bit
handles and turns unsigned tick counts negative — both of which fail quietly
rather than raising, which is the worst way for an observer to be wrong.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Handles are pointer-sized; tick counts are unsigned.
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.OpenInputDesktop.restype = wintypes.HDESK
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.CloseDesktop.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HDESK]
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.GetTickCount.argtypes = []

DESKTOP_SWITCHDESKTOP = 0x0100
_TICK_WRAP = 0xFFFFFFFF


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.restype = wintypes.BOOL
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]


def _idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input.

    Both values are 32-bit unsigned millisecond counters that wrap every ~49
    days, so the difference is masked back into range — otherwise the first
    wrap after a long uptime reports an idle time of several weeks and the
    observer decides you are permanently away.
    """
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    delta = (kernel32.GetTickCount() - lii.dwTime) & _TICK_WRAP
    return delta / 1000.0


def _foreground() -> tuple[str, str]:
    """(process_name, window_title) of the foreground window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")

    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        if user32.GetWindowTextW(hwnd, buf, length + 1):
            title = buf.value or ""

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    app = ""
    if pid.value:
        try:
            import psutil
            app = psutil.Process(pid.value).name()
        except Exception:
            app = ""
    return (app, title)


def _session_locked() -> bool:
    """A locked workstation switches to the secure (Winlogon) desktop.

    `OpenInputDesktop` with DESKTOP_SWITCHDESKTOP fails against it, so a NULL
    handle is the lock signal. Fail *closed* — treat an unexpected error as
    locked — because a wrong answer here means recording a desktop we were not
    meant to see.
    """
    try:
        hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    except Exception:
        return True
    if not hdesk:
        return True
    user32.CloseDesktop(hdesk)
    return False


class WindowsObserver:
    name = "windows"

    def snapshot(self):
        from .base import Snapshot
        app, title = _foreground()
        return Snapshot(
            app=app,
            title=title,
            idle_secs=_idle_seconds(),
            locked=_session_locked(),
            extra={"observer": "windows"},
        )
