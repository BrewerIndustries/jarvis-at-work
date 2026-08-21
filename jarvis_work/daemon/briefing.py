"""Composes the briefing Claude pulls at the start of a conversation.

This is the push channel, implemented as a pull: a line in the project
instructions tells Claude to call `jarvis_briefing` first, so every new chat
opens already knowing what you're doing and what is outstanding — without any
automation touching the app.

It is kept deliberately small. This text is prepended to every conversation, so
every wasted token is paid for repeatedly. Point at depth, don't inline it.
"""
from __future__ import annotations

import time

MAX_OPEN_ITEMS = 8
MAX_RECENT_APPS = 5


def build_briefing(store) -> dict:
    now = time.time()
    current = store.current_snapshot()
    open_items = store.list_work_items(status="open", limit=MAX_OPEN_ITEMS)
    recent = store.timeline(since_ts=now - 3600, limit=200)

    apps: list[str] = []
    for row in reversed(recent):
        app = row.get("app") or ""
        if app and app not in apps:
            apps.append(app)
        if len(apps) >= MAX_RECENT_APPS:
            break

    lines: list[str] = []
    if current:
        age = int(now - current["ts"])
        where = current["app"] + (f" — {current['title']}" if current.get("title") else "")
        lines.append(f"Right now: {where} (as of {age}s ago)")
    if apps:
        lines.append("Last hour: " + ", ".join(apps))
    if open_items:
        lines.append(f"{len(open_items)} open work item(s):")
        lines += [f"  #{i['id']} [{i['project'] or 'unfiled'}] {i['title']}" for i in open_items]
    else:
        lines.append("No open work items.")
    lines.append("Deeper context is available — call recall(), today_timeline(), "
                 "or list_work_items() rather than asking the user to repeat themselves.")

    return {
        "generated_ts": now,
        "text": "\n".join(lines),
        "current": current,
        "open_item_count": len(open_items),
    }
