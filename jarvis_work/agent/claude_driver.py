"""Drives Claude Desktop on the VM through Windows UI Automation.

Selectors are configuration, not constants. Run `spike_uia.py` on the VM first
and paste what it finds into config.agent.yaml — Claude Desktop ships often and
the accessibility tree is not a stable contract, so when an update breaks this
the fix is rerunning the spike and updating config, not editing code.

Two write paths, tried in order:
  1. ValuePattern.SetValue on the composer — no focus needed, so the VM stays
     usable for other things while Jarvis works.
  2. Focus the window and send keystrokes — always works, steals focus.

The macOS ancestor of this file clicked at 95% of the window height and hoped.
This is the version that asks the app where its controls are.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("jarvis-work.driver")

STOP_BUTTON_HINTS = ("stop", "stop response", "stop generating")


class ClaudeDriverError(RuntimeError):
    pass


class ClaudeDriver:
    def __init__(self, cfg: dict):
        c = cfg.get("claude", {})
        self.composer_automation_id = c.get("composer_automation_id", "")
        self.composer_control_type = c.get("composer_control_type", "EditControl")
        self.composer_name = c.get("composer_name", "")
        self.new_chat_hotkey = c.get("new_chat_hotkey", "ctrl+n")
        self.send_delay = float(c.get("send_delay_seconds", 0.4))
        self.search_depth = int(c.get("search_depth", 12))
        self._auto = None

    # ── plumbing ─────────────────────────────────────────────────────────────
    @property
    def auto(self):
        if self._auto is None:
            try:
                import uiautomation
            except ImportError as e:
                raise ClaudeDriverError(
                    "uiautomation not installed — this must run on the Windows VM"
                ) from e
            self._auto = uiautomation
        return self._auto

    def _window(self):
        auto = self.auto
        try:
            import psutil
        except ImportError:
            psutil = None
        for w in auto.GetRootControl().GetChildren():
            try:
                if psutil and "claude" in psutil.Process(w.ProcessId).name().lower():
                    return w
            except Exception:
                continue
        raise ClaudeDriverError("No Claude Desktop window found on this machine")

    def _find(self, win, predicate, max_depth: int | None = None):
        """Breadth-first search of the UIA tree. BFS not DFS: the controls we
        want (composer, stop button) sit near the top of a deep Electron tree,
        and DFS would spend its whole node budget in the message list."""
        auto = self.auto
        depth_cap = max_depth or self.search_depth
        queue = [(win, 0)]
        seen = 0
        while queue and seen < 3000:
            ctrl, depth = queue.pop(0)
            seen += 1
            if depth > depth_cap:
                continue
            try:
                if predicate(ctrl):
                    return ctrl
                queue.extend((ch, depth + 1) for ch in ctrl.GetChildren())
            except Exception:
                continue
        return None

    def _composer(self, win):
        auto = self.auto

        def matches(c):
            try:
                if self.composer_automation_id and c.AutomationId == self.composer_automation_id:
                    return True
                if self.composer_name and c.Name == self.composer_name:
                    return True
                # Fallback heuristic: an editable control that supports ValuePattern.
                if c.ControlTypeName == self.composer_control_type:
                    return bool(c.GetPattern(auto.PatternId.ValuePattern))
            except Exception:
                return False
            return False

        ctrl = self._find(win, matches)
        if ctrl is None:
            raise ClaudeDriverError(
                "Could not locate Claude's composer. Rerun spike_uia.py and update "
                "composer_automation_id / composer_name in config.agent.yaml."
            )
        return ctrl

    # ── read ─────────────────────────────────────────────────────────────────
    def state(self) -> dict:
        """Is Claude idle or generating? Detected by the presence of a stop button."""
        win = self._window()
        auto = self.auto

        def is_stop(c):
            try:
                return (c.ControlTypeName == "ButtonControl"
                        and (c.Name or "").strip().lower() in STOP_BUTTON_HINTS)
            except Exception:
                return False

        generating = self._find(win, is_stop, max_depth=self.search_depth) is not None
        return {"window_title": win.Name, "generating": generating,
                "state": "generating" if generating else "idle"}

    def read_conversation(self, limit: int = 20) -> list[str]:
        """Best-effort transcript scrape from the accessibility tree.

        Returns visible text blocks in document order. This is a view of what is
        rendered, so it sees only what is scrolled into the virtualised list —
        it is not a substitute for the conversation history, and shouldn't be
        treated as complete.
        """
        win = self._window()
        blocks: list[str] = []
        queue = [(win, 0)]
        seen = 0
        while queue and seen < 4000:
            ctrl, depth = queue.pop(0)
            seen += 1
            if depth > self.search_depth + 6:
                continue
            try:
                if ctrl.ControlTypeName == "TextControl":
                    txt = (ctrl.Name or "").strip()
                    if len(txt) > 1:
                        blocks.append(txt)
                queue.extend((ch, depth + 1) for ch in ctrl.GetChildren())
            except Exception:
                continue
        return blocks[-limit:]

    # ── write ────────────────────────────────────────────────────────────────
    def send(self, text: str, new_chat: bool = False) -> dict:
        if not text.strip():
            raise ClaudeDriverError("Refusing to send empty text")

        auto = self.auto
        win = self._window()

        if new_chat:
            win.SetActive()
            time.sleep(0.3)
            auto.SendKeys(self._hotkey_to_keys(self.new_chat_hotkey))
            time.sleep(0.8)
            win = self._window()

        composer = self._composer(win)

        # Path 1 — no focus required.
        try:
            vp = composer.GetPattern(auto.PatternId.ValuePattern)
            vp.SetValue(text)
            time.sleep(self.send_delay)
            readback = ""
            try:
                readback = composer.GetPattern(auto.PatternId.ValuePattern).Value or ""
            except Exception:
                pass
            if text[:40] in readback:
                composer.SendKeys("{Enter}", waitTime=0.05)
                return {"ok": True, "mode": "valuepattern", "focus_stolen": False}
        except Exception as e:
            logger.debug("ValuePattern path failed: %s", e)

        # Path 2 — focus and type. Always works, takes the foreground.
        try:
            win.SetActive()
            time.sleep(0.3)
            composer.Click(simulateMove=False)
            time.sleep(0.2)
            auto.SendKeys(_escape_sendkeys(text), interval=0.005)
            time.sleep(self.send_delay)
            auto.SendKeys("{Enter}")
            return {"ok": True, "mode": "keystrokes", "focus_stolen": True}
        except Exception as e:
            raise ClaudeDriverError(f"Both send paths failed: {e}") from e

    @staticmethod
    def _hotkey_to_keys(hotkey: str) -> str:
        parts = [p.strip().lower() for p in hotkey.split("+")]
        mods = {"ctrl": "{Ctrl}", "alt": "{Alt}", "shift": "{Shift}", "win": "{Win}"}
        out = "".join(mods[p] for p in parts if p in mods)
        tail = [p for p in parts if p not in mods]
        return out + (tail[0] if tail else "")


def _escape_sendkeys(text: str) -> str:
    """uiautomation's SendKeys treats {}()+^%~ as control characters."""
    for ch in "{}()+^%~":
        text = text.replace(ch, "{" + ch + "}")
    return text
