# Handoff

**You are Claude, picking up development of Jarvis at Work on the Windows work
machine.** This project was designed and scaffolded on a Mac, which could not
run most of what it produced. Read this before changing anything — it is the
context that isn't recoverable from the code.

---

## What this is, in one paragraph

Dan uses Claude constantly. The friction isn't writing prompts, it's that every
thought forces a filing decision — new chat, existing thread, which project —
made before he's started thinking about the actual problem and with incomplete
memory of what already exists. This project is the dispatcher for that: it
watches what he's doing, keeps a work-item registry, feeds all of it to Claude
Desktop over MCP, and can drive a *second* Claude Desktop on a Hyper-V VM. The
key move is that context lives in Jarvis rather than in a chat, which makes
starting a new chat free — and that is what makes the filing question stop
mattering.

---

## Read this before you assume something is broken

**Most of this code has never run.** The Mac could exercise the daemon, store,
redaction, briefing, and the whole MCP surface — that's it. Everything below is
written-but-unexercised, and a failure there is expected, not mysterious:

| Component | State | First failure to expect |
|---|---|---|
| `observers/windows.py` | never run on Windows | psutil name lookup on protected processes |
| `agent/spike_uia.py` | never run | an empty tree if Chromium a11y is lazy |
| `agent/claude_driver.py` | never run | selectors are blank until the spike fills them |
| `agent/uia_bridge.py` | never run | refuses everything until `bridge.token` is set |
| `llm/brain.py`, `llm/triage.py` | never called with a real key | first live call is unproven |

If something in that table fails, fix it — don't assume the design is wrong.
If something in the *verified* set fails, be more suspicious; it worked once.

---

## The gating step — do this first

```powershell
python -m jarvis_work.agent.spike_uia --depth 12 --write "hello from jarvis"
```

Claude Desktop is Electron, so it *should* expose a Chromium accessibility tree
through Windows UI Automation. Whether it actually does decides the entire VM
half of this project. Do not build anything else on the agent side until you
know.

- **RICH** → paste the printed `composer_automation_id` / `composer_name` into
  `config.agent.yaml` and proceed.
- **THIN** → retry at `--depth 16` before concluding anything.
- **EMPTY** → relaunch Claude as `Claude.exe --force-renderer-accessibility`
  and rerun. Still empty means UIA is not viable and the fallback is coordinate
  clicking — **stop and tell Dan** rather than quietly building the worse thing.

Also note whether the write test needed focus. `ValuePattern.SetValue` working
without focus means Jarvis can drive Claude while the VM is used for other
things; needing focus makes the VM single-purpose. Either is workable; it
changes what to promise.

---

## Decisions already made — don't relitigate these

These were argued through properly. If you think one is wrong, say so
explicitly rather than quietly building around it.

**Only Claude Desktop gets GUI automation.** Outlook has COM. Gmail and Drive
have APIs. Explorer is a file manager and Python does files. Claude Desktop is
the sole application here with *no* API — no way to create a chat, post to a
thread, or read one back — and that is the entire justification for the VM.
Build tier 1 (APIs) and tier 2 (local artifacts: Outlook COM, OneDrive folder
watching) before any new GUI automation.

**The VM holds no corporate credentials.** Not Outlook, not OneDrive, not SSO,
no domain join. It signs into Claude and nothing else. This is what makes the
whole approach defensible: everything the agent can touch was handed to it
deliberately over the bridge. Do not "simplify" by logging the VM into work
accounts.

**Why the second machine is safe at all:** the MFA / Conditional Access /
impossible-travel objections all apply to the *corporate* identity. Claude
Desktop signs in with the Anthropic account, and it's a **Claude Team** seat
(not Enterprise), so multiple devices are normal. The one real cost is that the
VM consumes Dan's seat usage — which is why the router is deliberately biased
toward filing over dispatching.

**Read-only by default.** No shell tool, no self-modification, no sending mail,
no deleting anything. The home `jarvis` repo has a known systemic problem where
safety is decided by the model rather than enforced in code; this project does
not inherit it. What Jarvis can't do is *absent*, not discouraged in a prompt.
Keep it that way.

**Escalation is model-decided.** Every structured decision carries a
`confidence`; a low score re-runs on Opus. Don't replace this with a keyword
heuristic — a model reporting it's guessing is better signal than any rule.

---

## Traps that will cost you an afternoon

**The cache-prefix trap.** `llm/brain.py` puts the system prompt behind a
`cache_control` breakpoint with a 1h TTL. Prompt caching is a *prefix match* —
one changed byte invalidates everything after it. `triage.SYSTEM` is frozen on
purpose; the clock, the snapshot, and the timeline all go in the user turn.
Interpolating a date or a count into `SYSTEM` costs full price on every call
while looking like it works. `brain.last_usage["cache_read"]` is the check.

**Redaction happens at capture, not at display.** `redact.py` runs before
SQLite. A blind app produces no row at all. This means a later bug in a read
path cannot leak what was never written — and it also means anything Dan
forgets to add to `blind_apps` is already on disk by the time he thinks of it.
Never move redaction to the read side.

**The MCP shim is stateless on purpose.** Claude Desktop kills and relaunches it
at will. Every tool forwards to the daemon over localhost. Do not add caching,
state, or a database to `mcp/server.py` — it will not survive.

**ctypes needs explicit argtypes.** An undeclared return defaults to a *signed
32-bit int*, which truncates 64-bit handles and turns unsigned tick counts
negative. Three such bugs were already fixed in `observers/windows.py` (commit
`09a83eb`) and every one failed *silently* — wrong data, no exception. Declare
`argtypes`/`restype` on every new Win32 call you add.

**MCP tool descriptions are the interface.** The docstrings in
`mcp/server.py` are what Claude reads to decide whether to call a tool. They're
written for that audience deliberately. Editing one for brevity can silently
stop a tool from being invoked.

---

## Conventions in this ecosystem

- **Repo:** `BrewerIndustries/jarvis-at-work` (a personal account, not an org —
  the older runbook says "org" and is wrong).
- **Git:** push to `dev` freely. `main` **only** via a PR Dan approves — never
  fast-forward or force-push it. Don't hold finished work locally; commit and
  push to `dev` without being asked.
- **`.jarvis.json`** drives the project dashboard. A cron reads it every 15 min
  via the GitHub API — dev branch → dev registry, main → prod. Update `status`
  when a lane genuinely changes.
- **README stays current.** Dan expects it updated after any meaningful change.
  The status table in it is load-bearing — it's how he knows what's real.
- **Ask before restarting anything Jarvis-related** on the home server; he may
  be mid-conversation with it.

---

## Layout

```
jarvis_work/
  config.py       config + env overrides (ANTHROPIC_API_KEY wins over the file)
  redact.py       scrubbing, at capture
  daemon/         app.py (API), store.py (SQLite), briefing.py, agent_client.py
  observers/      windows.py (real), darwin.py (Mac dev), loop.py (dedup)
  llm/            brain.py (tiered Claude), triage.py (the dispatcher)
  mcp/            server.py — 9 tools, stdio, stateless
  agent/          ON THE VM: spike_uia.py, claude_driver.py, uia_bridge.py
docs/             ARCHITECTURE.md, INSTALL-WINDOWS.md, HYPER-V-SETUP.md
```

## How to check you haven't broken anything

There is no test suite yet — **adding one is a reasonable first contribution.**
Until then:

```powershell
python -m compileall -q jarvis_work           # agent/ + observers/ included
python -m jarvis_work.daemon.app              # should log observer/db/agent/brain
curl.exe http://127.0.0.1:8765/health
curl.exe http://127.0.0.1:8765/briefing       # switch apps first, then re-check
```

For the MCP surface, connect a client over stdio, list tools (expect 9), and
call `jarvis_briefing`. The daemon must be running or every tool returns an
"unreachable" string rather than throwing.

---

## Open questions

- **Does the tenant allow an app registration + admin consent for Graph?**
  Transcript scopes are admin-consent-only. This decides whether tier 1 exists
  at all, and it's worth answering before building toward it.
- **Classic Outlook or New Outlook?** COM automation — the single highest-value
  tier-2 integration — exists only on classic. New Outlook dropped it.
- **Does `ValuePattern` write without focus?** The spike answers this.

## Where to go next

`BACKLOG.md` is ordered. The short version: run the spike, live-test the brain,
run the observer on real Windows, then build the capture UI (global hotkey plus
a box — capture must cost nothing at the moment of capture; routing happens
after). Resist adding GUI automation for anything with an API.

---

*Written by Claude on the Mac, 2026-08-21, at the end of the session that
scaffolded this repo. Everything above was true at commit `09a83eb`.*
