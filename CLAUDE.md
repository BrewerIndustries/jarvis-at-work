# Jarvis at Work — working notes

**Read [HANDOFF.md](HANDOFF.md) before your first substantive change.** It has the
reasoning behind the design, what has and hasn't been verified, and the traps.
This file is the short version that loads every session.

## What it is

A Windows work-machine assistant: an ambient daemon that watches what Dan is
doing, keeps a work-item registry, exposes it to Claude Desktop over MCP, and
drives a second Claude Desktop on a Hyper-V VM via UI Automation.

## Invariants — don't break these without saying so out loud

- **Read-only by default.** No shell tool, no self-modification, no sending
  mail, no deleting. What Jarvis can't do is absent from the code, not
  discouraged in a prompt.
- **The agent VM holds no corporate credentials.** It signs into Claude and
  nothing else.
- **GUI automation is only for Claude Desktop** — the one app here with no API.
  Everything else (Outlook → COM, Google/Graph → APIs, files → Python) uses a
  headless path.
- **Redaction happens at capture**, before SQLite, never at display.
- **`triage.SYSTEM` is frozen.** It sits behind a prompt-cache breakpoint;
  interpolating anything volatile into it silently costs full price on every
  call. Volatile context goes in the user turn.
- **`mcp/server.py` is stateless.** Claude Desktop kills and relaunches it at
  will. No caching, no state.
- **Declare `argtypes`/`restype` on every Win32 ctypes call.** Undeclared
  returns default to signed 32-bit and truncate handles — silently.

## Verified vs not

Verified on macOS: daemon, store, redaction, briefing, all 9 MCP tools.
**Not yet run anywhere:** `observers/windows.py`, everything in `agent/`, and
`llm/`. Expect failures there; they aren't mysteries.

The gating unknown is whether Claude Desktop's accessibility tree is drivable —
`python -m jarvis_work.agent.spike_uia --write "test"` answers it, and the whole
VM half depends on the answer.

## Workflow

- Push to `dev` freely. `main` only via a PR Dan approves — never force-push it.
- Commit and push finished work without being asked; don't sit on it locally.
- Keep `README.md` current, especially its status table.
- `.jarvis.json` feeds the project dashboard; update `status` when a lane really
  changes.

## Checks

```powershell
python -m compileall -q jarvis_work
python -m jarvis_work.daemon.app
curl.exe http://127.0.0.1:8765/health
curl.exe http://127.0.0.1:8765/briefing
```

No test suite yet. Adding one is a welcome first contribution.
