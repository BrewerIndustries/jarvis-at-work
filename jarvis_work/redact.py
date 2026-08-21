"""Redaction applied at the point of capture, not at the point of display.

On a work machine the observer sees window titles that may name a client, a
salary, or a case number. Anything filtered here never reaches SQLite, so a
later bug in a read path cannot leak what was never written.
"""
from __future__ import annotations

import re

# Patterns worth scrubbing out of any captured string regardless of app.
_SCRUBBERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[card]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (re.compile(r"\b(?:sk|pk|ghp|xox[baprs])[-_][A-Za-z0-9._-]{16,}\b"), "[token]"),
]


class Redactor:
    def __init__(self, blind_apps: list[str] | None = None,
                 blind_title_patterns: list[str] | None = None):
        self.blind_apps = {a.lower() for a in (blind_apps or [])}
        self.blind_titles = [re.compile(p) for p in (blind_title_patterns or [])]

    def app_is_blind(self, app: str) -> bool:
        """True when this app should produce no observation at all."""
        a = (app or "").lower()
        return any(b in a for b in self.blind_apps)

    def title(self, title: str) -> str:
        if not title:
            return ""
        if any(p.search(title) for p in self.blind_titles):
            return "(redacted)"
        return self.text(title)

    def text(self, s: str) -> str:
        if not s:
            return ""
        for pat, repl in _SCRUBBERS:
            s = pat.sub(repl, s)
        return s
