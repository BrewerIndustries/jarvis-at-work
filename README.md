# Jarvis at Work

A work-machine assistant for Windows. It watches what you're doing, keeps the
things you've handed it, hands all of that to Claude Desktop over MCP — and
drives a *second* Claude Desktop on a VM so it can work without stealing your
keyboard.

It borrows the spine of the home `jarvis` repo (ambient loop, memory, proactivity)
but is a separate project: different OS, different threat model, no smart home,
no wake word, and a different centre of gravity.

## The idea

The painful part of working with Claude is not typing the prompt. It is that
every thought forces a filing decision — new chat, existing thread, which
project, or a whole new project — made before you have started thinking about
the actual problem, and made with incomplete memory of what already exists.

Jarvis at Work is the dispatcher for that. You capture the thought; it decides
where it goes, using context you don't have to hand: what's on your screen, what
you were doing an hour ago, what's already open.

And because the context lives in Jarvis rather than in a chat, **starting a new
chat costs nothing** — which is what makes the filing question stop mattering.

## Status

**Early — the laptop half works, the VM half is unproven.**

| Component | State |
|---|---|
| Daemon (store, observer loop, API) | Built, tested |
| Redaction at capture | Built, tested |
| MCP shim (9 tools) | Built, tested end-to-end over stdio |
| Briefing composer | Built, tested |
| Windows observer | Written, **not yet run on Windows** |
| Brain (Sonnet→Opus routing) | Written, **not yet run against the live API** |
| Agent bridge + UIA driver | Written, **blocked on the spike** |
| Hyper-V VM | Documented, not built |

The critical unknown is whether Claude Desktop's Electron accessibility tree is
rich enough to drive by named control. `jarvis_work/agent/spike_uia.py` answers
that in about a minute, and everything on the VM side depends on the answer.

## Picking this up on another machine

[HANDOFF.md](HANDOFF.md) — written for whoever (or whatever) continues
development from here: the decisions already settled, what's verified versus
merely written, and the traps. [CLAUDE.md](CLAUDE.md) is the short version that
loads automatically in Claude Code.

## Layout

```
jarvis_work/
  config.py          config + env overrides
  redact.py          scrubbing at the point of capture
  daemon/            long-lived: store, API, briefing, agent client
  observers/         windows.py (real) + darwin.py (dev) behind one interface
  llm/               brain.py (tiered Claude) + triage.py (the dispatcher)
  mcp/               stdio shim Claude Desktop launches
  agent/             runs on the VM: spike_uia.py, claude_driver.py, uia_bridge.py
docs/
  ARCHITECTURE.md    why it's split the way it is
  INSTALL-WINDOWS.md the laptop half
  HYPER-V-SETUP.md   the VM half
```

## Quick start

Laptop: [docs/INSTALL-WINDOWS.md](docs/INSTALL-WINDOWS.md).
VM: [docs/HYPER-V-SETUP.md](docs/HYPER-V-SETUP.md) — but run the spike first.

## MCP tools

| Tool | What it does |
|---|---|
| `jarvis_briefing` | current context + recent activity + open items |
| `current_context` | what's on screen right now |
| `today_timeline` | chronological activity for the last N hours |
| `recall` | search durable memory |
| `remember` | save a durable fact |
| `list_work_items` | the registry |
| `file_work_item` | record something without routing it |
| `capture` | hand it over and let Jarvis decide what happens |
| `update_work_item` | mark done/blocked, append a progress note |

## The brain

Sonnet 5 by default, Opus 5 on escalation — and escalation is decided by the
model, not by us: every structured decision carries a `confidence`, and a low
score re-runs the question on the deep tier.

The system prompt is frozen behind a 1h cache breakpoint; everything volatile
goes after it. Watch `usage.cache_read_input_tokens` — a persistent zero means
something changing crept into the prefix.

## What it won't do

No shell tool. No self-modification. No sending mail, no deleting files, no
touching corporate systems. The agent VM holds no work credentials at all — it
can only act on what Jarvis deliberately handed it. These are absences in the
code, not instructions in a prompt.
