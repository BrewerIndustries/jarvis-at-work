"""The handler. Decides where a captured thought goes so you don't have to.

This is the whole point of the project in one file. You say "have Claude work
on this" and something has to answer the questions you were previously
answering yourself, badly, before you'd even started thinking: new chat or
existing thread? which project? is this even worth a chat, or should it just be
written down?

The routing decision is made against your live context — what is on screen,
what you were doing an hour ago, what is already open — which is exactly the
information you don't have to hand when you're the one deciding.
"""
from __future__ import annotations

import datetime as dt
import json
from enum import Enum

from pydantic import BaseModel, Field

from .brain import Brain, Tier


class Action(str, Enum):
    FILE_ONLY = "file_only"        # write it down; no conversation needed
    DISPATCH = "dispatch"          # send to Claude on the agent VM now
    ANSWER_DIRECTLY = "answer"     # small enough that Jarvis just answers
    ASK_USER = "ask"               # genuinely ambiguous — don't guess


class Routing(BaseModel):
    action: Action = Field(description="What to do with this capture")
    title: str = Field(description="Short imperative title for the work item")
    project: str = Field(default="", description="Project bucket, or empty if unfiled")
    new_chat: bool = Field(default=True, description="Start a new chat rather than continue the open one")
    prompt: str = Field(default="", description="The fully-formed prompt to send to Claude, if dispatching")
    reason: str = Field(description="One sentence: why this routing")
    confidence: float = Field(description="0.0-1.0 confidence in this routing")


# Frozen. Every byte here is part of the cached prefix — do not interpolate
# dates, names, or counts into it. Volatile context goes in the user turn.
SYSTEM = """You are the dispatcher for Jarvis, a work assistant running on Dan's \
Windows work machine. Dan captures a thought in one box and you decide where it goes, \
so he never has to choose between "new chat", "existing thread", or "new project" \
himself.

You will be given: the capture, what is on his screen right now, what he has been \
doing recently, and the work items already tracked.

Choose exactly one action:

- file_only: a note, a reminder, or a commitment. Nothing to discuss yet. Prefer this \
  when in doubt — filing is cheap and reversible, a dispatched chat is neither.
- dispatch: real work Claude can start on now. Write `prompt` as a complete, \
  self-contained brief including the relevant context from what he was doing — the \
  receiving chat has no memory of any of this.
- answer: trivially answerable from the context you already have.
- ask: genuinely ambiguous, or it would touch something irreversible. Say what you'd \
  need to know.

Set new_chat=false only when the capture clearly continues a work item already open.

Match `project` to an existing project on the tracked list when the capture plainly \
belongs to one; leave it empty rather than inventing a new bucket for a one-off.

Be honest in `confidence`. A low score routes the decision to a stronger model, which \
is the correct outcome when you are guessing — do not inflate it."""


def _context_block(briefing: dict, open_items: list[dict], capture: str) -> str:
    """The volatile half of the prompt. Everything that changes call to call
    lives here, after the cache breakpoint, never in SYSTEM."""
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    items = [{"id": i["id"], "title": i["title"], "project": i.get("project", ""),
              "status": i.get("status", "")} for i in open_items]
    return (
        f"Current time: {now}\n\n"
        f"--- Live context ---\n{briefing.get('text', '(none)')}\n\n"
        f"--- Tracked work items ---\n{json.dumps(items, indent=2)}\n\n"
        f"--- The capture ---\n{capture}"
    )


def route(brain: Brain, capture: str, briefing: dict,
          open_items: list[dict]) -> tuple[Routing, bool]:
    """Route one capture. Returns (routing, escalated)."""
    return brain.decide(SYSTEM, _context_block(briefing, open_items, capture),
                        Routing, tier=Tier.DEFAULT)
