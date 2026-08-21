"""MCP shim — the channel Claude Desktop uses to reach Jarvis.

Claude Desktop launches this over stdio and may kill and relaunch it whenever
it likes, so it holds no state: every tool is a thin forward to the daemon on
localhost. If the daemon is down, tools say so plainly rather than failing in
a way Claude will try to work around.

Tool docstrings are the whole interface Claude sees, and they are what decides
whether a tool gets called at the right moment. They are written for that
audience, not for us.

Wire it up in claude_desktop_config.json — see docs/INSTALL-WINDOWS.md.
"""
from __future__ import annotations

import json
import sys

import httpx
from mcp.server.fastmcp import FastMCP

from ..config import load_config

cfg = load_config()
DAEMON = cfg["mcp"]["daemon_url"].rstrip("/")
TIMEOUT = 10.0

mcp = FastMCP("jarvis-at-work")


def _get(path: str, **params) -> dict:
    try:
        r = httpx.get(f"{DAEMON}{path}", params=params or None, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"ok": False, "error": f"Jarvis daemon unreachable at {DAEMON}: {e}"}


def _post(path: str, payload: dict) -> dict:
    try:
        r = httpx.post(f"{DAEMON}{path}", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"ok": False, "error": f"Jarvis daemon unreachable at {DAEMON}: {e}"}


def _err(res: dict) -> str | None:
    if not res.get("ok"):
        return f"Jarvis is not available right now. {res.get('error', 'Unknown error.')}"
    return None


# ── read ─────────────────────────────────────────────────────────────────────
@mcp.tool()
def jarvis_briefing() -> str:
    """Get Dan's current working context: what he is doing right now, what he has
    been doing this past hour, and which work items are open.

    Call this at the START of a conversation, before asking him what he is
    working on or what he means by "this" — the answer is usually already here.
    """
    res = _get("/briefing")
    return _err(res) or res.get("text", "(no context yet)")


@mcp.tool()
def current_context() -> str:
    """What is on Dan's screen right now — the foreground application and window
    title. Use this to resolve vague references like "this doc", "that ticket",
    or "what I'm looking at".
    """
    res = _get("/context/current")
    if e := _err(res):
        return e
    c = res.get("context")
    if not c:
        return "No context recorded yet — the observer may have just started."
    title = f" — {c['title']}" if c.get("title") else ""
    return f"{c['app']}{title} (idle {int(c['idle_secs'])}s)"


@mcp.tool()
def today_timeline(hours: float = 8.0) -> str:
    """A chronological list of what Dan worked on over the last N hours, as
    app + window title with timestamps.

    Use for "what did I do today", "what was I working on before that meeting",
    reconstructing how long something took, or writing a status update.
    """
    import datetime as _dt
    res = _get("/timeline", hours=hours)
    if e := _err(res):
        return e
    entries = res.get("entries", [])
    if not entries:
        return f"Nothing recorded in the last {hours} hours."
    lines = []
    for row in entries:
        t = _dt.datetime.fromtimestamp(row["ts"]).strftime("%H:%M")
        title = f" — {row['title']}" if row.get("title") else ""
        lines.append(f"{t}  {row['app']}{title}")
    return "\n".join(lines[-200:])


@mcp.tool()
def recall(query: str) -> str:
    """Search Jarvis's durable memory for facts about Dan's work — decisions,
    names, conventions, preferences, who-owns-what.

    Call this BEFORE saying you lack context about a project, a person, or a
    prior decision. Memory persists across conversations, so the answer may be
    here even though this chat has never seen it.
    """
    res = _get("/memory", q=query)
    if e := _err(res):
        return e
    items = res.get("items", [])
    if not items:
        return f"Nothing in memory matching '{query}'."
    return "\n".join(f"- {i['fact']}" + (f"  [{i['tags']}]" if i.get("tags") else "")
                     for i in items)


@mcp.tool()
def list_work_items(status: str = "open") -> str:
    """List tracked work items. `status` is one of: open, done, all.

    These are the things Dan has handed to Jarvis to keep track of — the
    registry that makes it unnecessary to remember which chat something was in.
    """
    res = _get("/work_items", status=status, limit=100)
    if e := _err(res):
        return e
    items = res.get("items", [])
    if not items:
        return f"No {status} work items."
    out = []
    for i in items:
        proj = f"[{i['project']}] " if i.get("project") else ""
        out.append(f"#{i['id']} {proj}{i['title']} ({i['status']})")
        if i.get("detail"):
            detail = i["detail"] if isinstance(i["detail"], str) else json.dumps(i["detail"])
            out.append(f"      {detail[:300]}")
    return "\n".join(out)


# ── write ────────────────────────────────────────────────────────────────────
@mcp.tool()
def remember(fact: str, tags: str = "") -> str:
    """Save a durable fact to Jarvis's memory so future conversations know it
    without being told again.

    Use for decisions made, conventions agreed, names and ownership, and
    anything Dan says in a way that implies it should stick ("we always...",
    "remember that...", "from now on..."). `tags` is a free-form comma-separated
    string used for later retrieval.
    """
    res = _post("/memory", {"fact": fact, "tags": tags, "source": "claude"})
    return _err(res) or f"Saved to memory (#{res['id']})."


@mcp.tool()
def file_work_item(title: str, detail: str = "", project: str = "") -> str:
    """File a piece of work into Jarvis's registry so it is tracked outside this
    conversation and survives it.

    This is the answer to "have Claude work on this" — instead of deciding which
    chat or project something belongs in, file it here and it can be picked up
    from any future conversation. Use when Dan describes something to do later,
    commits to an action, or when a conversation produces a follow-up.
    """
    res = _post("/work_items", {"title": title, "detail": detail,
                                "project": project, "source": "claude"})
    return _err(res) or f"Filed as work item #{res['id']}."


@mcp.tool()
def capture(text: str) -> str:
    """Hand something to Jarvis and let it decide what happens next — whether it
    is just filed, answered, or dispatched to Claude on the agent machine.

    Use this when Dan says "have Jarvis handle this", "hand this off", or
    describes work without saying where it should go. Unlike file_work_item,
    which just records, this routes: it reads his current context and picks the
    destination so he does not have to.
    """
    res = _post("/capture", {"text": text})
    if e := _err(res):
        return e
    if not res.get("routed"):
        return f"Filed as work item #{res['work_item']} (routing unavailable)."
    parts = [f"Routed: {res['action']} — {res['reason']}",
             f"Filed as #{res['work_item']} \"{res['title']}\""
             + (f" in {res['project']}" if res.get("project") else "")]
    if res.get("escalated"):
        parts.append("(escalated to the deep model — the first pass was unsure)")
    if d := res.get("dispatched"):
        parts.append("Sent to Claude on the agent VM." if d.get("ok")
                     else f"Not sent: {d.get('error')}")
    return "\n".join(parts)


@mcp.tool()
def update_work_item(item_id: int, status: str = "", note: str = "") -> str:
    """Update a tracked work item: set `status` (open/done/blocked) and/or append
    a `note` recording progress. Use when Dan says something is finished,
    blocked, or has moved on.
    """
    payload = {k: v for k, v in (("status", status or None), ("note", note or None))
               if v is not None}
    try:
        r = httpx.patch(f"{DAEMON}/work_items/{item_id}", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        res = r.json()
    except Exception as e:
        return f"Jarvis is not available right now. {e}"
    return _err(res) or f"Work item #{item_id} updated."


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
