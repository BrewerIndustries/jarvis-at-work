"""Windows eyes.

Notably simpler than the macOS original this borrows from: the foreground
window and its title come from plain Win32 calls with no permission grant,
where macOS needs Screen Recording before it will hand over a window title
at all.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .base import Snapshot

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _idle_seconds() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return max(0.0, (kernel32.GetTickCount() - lii.dwTime) / 1000.0)


def _foreground() -> tuple[str, str]:
    """(process_name, window_title) of the foreground window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")

    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or ""

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    app = ""
    try:
        import psutil
        app = psutil.Process(pid.value).name()
    except Exception:
        app = ""
    return (app, title)


def _session_locked() -> bool:
    """A locked workstation shows the LogonUI desktop.

    Querying the input desktop is the reliable signal; if the handle can't be
    opened at all we're almost certainly on the secure desktop, i.e. locked.
    """
    try:
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_READOBJECTS
        if not hdesk:
            return True
        user32.CloseDesktop(hdesk)
        return False
    except Exception:
        return False


class WindowsObserver:
    name = "windows"

    def snapshot(self) -> Snapshot:
        app, title = _foreground()
        return Snapshot(
            app=app,
            title=title,
            idle_secs=_idle_seconds(),
            locked=_session_locked(),
            extra={"observer": "windows"},
        )
