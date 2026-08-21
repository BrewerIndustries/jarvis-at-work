# Architecture

Three processes on two machines. The split is deliberate — each boundary exists
because something on the other side is untrustworthy, unreliable, or short-lived.

```
WORK LAPTOP (Windows)                          AGENT VM (Hyper-V, Windows)
─────────────────────                          ──────────────────────────
observers ─┐                                   Claude Desktop
           ├─► daemon  ──── HTTP ───────────►  agent bridge (uia_bridge)
brain  ────┘   127.0.0.1:8765                    192.168.220.10:8766
  Claude API      │                                    │
  Sonnet→Opus     │  SQLite                            │ UI Automation
                  │  context / work items              ▼
                  │  memory / events               the composer,
                  │                                the transcript,
       Claude Desktop (yours)                      the send button
                  │  stdio
                  └── mcp shim ──► daemon
```

## Why three processes

**The daemon is long-lived** because the observer loop and the store must be.
It binds `127.0.0.1` only. Nothing reaches it from the network, including the VM
— the VM is talked *to*, never *from*.

**The MCP shim is short-lived** because Claude Desktop owns its lifecycle and
will kill and relaunch it whenever it feels like it. It therefore holds no state
at all: every tool is a forward to the daemon. Putting the store in the shim
would mean losing it on every Claude restart.

**The bridge lives on the VM** because UI Automation can only drive a desktop it
is logged into. It is the only component that listens on a network interface,
which is why it is also the smallest and the only one with a shared-secret check.

## The two channels to Claude

They run in opposite directions and neither replaces the other.

**In — MCP.** Claude Desktop pulls context, memory, and the work registry. Fully
supported, no automation. The push problem is solved by making the pull
automatic: a line in the project instructions tells Claude to call
`jarvis_briefing` at the start of every conversation, so a new chat opens
already knowing what you're doing. That is the trick that makes new chats cheap
— and cheap new chats are what makes "which chat does this go in?" stop being a
question worth asking.

**Out — UI Automation.** The daemon drives a *second* Claude Desktop on the VM.
This exists because Claude Desktop has no API: no way to create a chat, post to a
thread, or read one back. Every other application in this stack (Outlook, Drive,
Explorer) has a better non-GUI path and should use it. Claude Desktop is the one
genuine exception, which is the entire justification for the VM.

## The brain

Jarvis reasons with the Claude API — Sonnet 5 by default, escalating to Opus 5.
Escalation is not a heuristic we wrote: every structured decision returns a
`confidence`, and a low score re-runs the same question on the deep tier. The
model deciding it is out of its depth is a better signal than any rule.

The system prompt is frozen and cached with a 1h TTL; everything volatile — the
current snapshot, timestamps, the timeline — goes in the user turn after the
breakpoint. Prompt caching is a prefix match, so a clock in the system prompt
would silently cost full price on every call.

## Data boundaries

| Boundary | What crosses it | Why it's safe |
|---|---|---|
| Observer → store | app names, window titles | redacted at capture, never written if blind |
| Store → Claude Desktop | context, memory, work items | via MCP, localhost only, you asked for it |
| Daemon → VM | one prompt at a time | outbound only, audited before it leaves |
| VM → corporate systems | **nothing** | the VM has no work credentials at all |

That last row is the one that matters. The agent VM can only ever act on what
Jarvis deliberately handed it, which is a materially better story than a second
machine holding its own copy of your work identity.

## What this deliberately is not

- **Not an autonomous actor.** Nothing sends mail, deletes files, or touches
  corporate systems. The action surface is: observe, remember, file, and talk to
  Claude.
- **Not a second you.** The VM signs into Claude and nothing else.
- **Not model-decided safety.** The daemon has no shell tool and no self-modify
  path. What it cannot do is absent from the code, not discouraged in a prompt.
