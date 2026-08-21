"""The observer loop, run in-process by the daemon.

Deduplicates aggressively. A naive tick-every-5s writer produces ~17k rows a
day, almost all of them identical to the row before. We only write when the
foreground app or title actually changes (or once a minute regardless, so the
timeline still shows dwell), which turns a day into a few hundred meaningful
rows and makes the timeline readable by a model without truncation.
"""
from __future__ import annotations

import asyncio
import logging

from ..redact import Redactor
from .base import Observer

logger = logging.getLogger("jarvis-work.observer")

HEARTBEAT_SECONDS = 60.0


class ObserverLoop:
    def __init__(self, observer: Observer, store, redactor: Redactor,
                 interval: float = 5.0, capture_titles: bool = True):
        self.observer = observer
        self.store = store
        self.redactor = redactor
        self.interval = max(1.0, float(interval))
        self.capture_titles = capture_titles
        self.paused = False
        self._last_key: tuple[str, str] | None = None
        self._last_write: float = 0.0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="observer-loop")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                if not self.paused:
                    snap = await loop.run_in_executor(None, self.observer.snapshot)
                    self._maybe_write(snap, loop.time())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("observer tick failed: %s", e)
            await asyncio.sleep(self.interval)

    def _maybe_write(self, snap, now: float) -> None:
        if snap.locked or not snap.app:
            return
        # A blind app produces no row at all — not an app name, not a title.
        if self.redactor.app_is_blind(snap.app):
            return

        title = self.redactor.title(snap.title) if self.capture_titles else ""
        key = (snap.app, title)
        stale = (now - self._last_write) >= HEARTBEAT_SECONDS
        if key == self._last_key and not stale:
            return

        self.store.add_snapshot(app=snap.app, title=title, idle_secs=snap.idle_secs,
                                locked=snap.locked, extra=snap.extra)
        self._last_key = key
        self._last_write = now
