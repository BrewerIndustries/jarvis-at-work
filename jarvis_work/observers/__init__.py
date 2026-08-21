"""Platform-specific eyes. `get_observer()` returns the right one for the host."""
from __future__ import annotations

import sys

from .base import Observer, Snapshot, NullObserver


def get_observer() -> Observer:
    if sys.platform == "win32":
        from .windows import WindowsObserver
        return WindowsObserver()
    if sys.platform == "darwin":
        # Dev-only. Lets the daemon and the MCP shim be exercised end-to-end on
        # the Mac before any of this reaches the work laptop.
        from .darwin import DarwinObserver
        return DarwinObserver()
    return NullObserver()
