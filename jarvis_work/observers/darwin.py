"""macOS eyes — development only.

Exists so the daemon, the store, and the MCP shim can be built and exercised
on the Mac before the work laptop is involved. Uses CGWindowList rather than
NSWorkspace, which gets stuck on the app that was frontmost at process start
when there is no Cocoa run loop.
"""
from __future__ import annotations

import subprocess

from .base import Snapshot


def _foreground() -> tuple[str, str]:
    try:
        from Quartz import (CGWindowListCopyWindowInfo,
                            kCGWindowListOptionOnScreenOnly,
                            kCGWindowListExcludeDesktopElements,
                            kCGNullWindowID)
    except Exception:
        return ("", "")
    opts = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    for w in (CGWindowListCopyWindowInfo(opts, kCGNullWindowID) or []):
        if w.get("kCGWindowLayer", 0) == 0:
            name = w.get("kCGWindowOwnerName", "") or ""
            if name:
                return (name, w.get("kCGWindowName", "") or "")
    return ("", "")


def _idle_seconds() -> float:
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                return int(line.split("=")[-1].strip()) / 1_000_000_000
    except Exception:
        pass
    return 0.0


class DarwinObserver:
    name = "darwin"

    def snapshot(self) -> Snapshot:
        app, title = _foreground()
        return Snapshot(app=app, title=title, idle_secs=_idle_seconds(),
                        locked=False, extra={"observer": "darwin"})
