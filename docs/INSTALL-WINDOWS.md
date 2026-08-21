# Installing the client on the work laptop

This is the half that runs on your actual machine: the observer, the store, the
brain, and the MCP shim Claude Desktop talks to. The agent VM is separate — see
[HYPER-V-SETUP.md](HYPER-V-SETUP.md) — and you do not need it to get value from
this half.

## 1. Install

```powershell
winget install Python.Python.3.12 Git.Git
git clone <your-repo-url> C:\jarvis-at-work
cd C:\jarvis-at-work
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
```

## 2. Configure

Edit `config.yaml`. The parts that matter on day one:

```yaml
observer:
  interval_seconds: 5
  capture_titles: true
  blind_apps: ["1Password", "Windows Security"]   # add your own
  blind_title_patterns: ["(?i)payroll", "(?i)salary"]
```

**Spend two minutes on `blind_apps` and `blind_title_patterns` before you start
it.** Redaction happens at capture, so anything you list here never reaches the
database at all — but anything you forget is already written by the time you
think of it.

For the API key, prefer the environment over the file:

```powershell
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

## 3. Run the daemon

```powershell
.\.venv\Scripts\python -m jarvis_work.daemon.app
```

Check it:

```powershell
curl.exe http://127.0.0.1:8765/health
curl.exe http://127.0.0.1:8765/briefing
```

Switch between a few apps, wait a few seconds, and hit `/briefing` again — you
should see them. That's the observer working.

## 4. Connect Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "C:\\jarvis-at-work\\.venv\\Scripts\\python.exe",
      "args": ["-m", "jarvis_work.mcp.server"],
      "cwd": "C:\\jarvis-at-work"
    }
  }
}
```

Restart Claude Desktop fully (quit from the tray, not just the window). You
should see the Jarvis tools appear. Ask it "what am I working on?" — it should
call `jarvis_briefing` rather than asking you.

## 5. Make the briefing automatic

This is the step that makes it feel like an assistant instead of a database.
In your Claude project's custom instructions, add:

```
At the start of each conversation, call jarvis_briefing to load my current
working context. Use recall() before telling me you lack context about a
project or decision. When I describe work to do later, file it with capture().
```

Now every new chat opens already knowing what you're doing — and starting a new
chat costs nothing, which is the whole point.

## 6. Autostart

Task Scheduler → Create Task:

- **Trigger:** At log on
- **Action:** `C:\jarvis-at-work\.venv\Scripts\pythonw.exe` with arguments
  `-m jarvis_work.daemon.app`, starting in `C:\jarvis-at-work`
- Leave "run whether user is logged on or not" **unticked** — the observer needs
  a real interactive session to see anything.

`pythonw.exe` rather than `python.exe` keeps it from opening a console window.

## 7. Later: connect the agent VM

Once the VM is built and its bridge answers, add to `config.yaml`:

```yaml
agent:
  bridge_url: "http://192.168.220.10:8766"
  bridge_token: "<the same token as the VM>"
  enabled: true
```

Restart the daemon and check:

```powershell
curl.exe http://127.0.0.1:8765/agent/health
```

## Turning it off

```powershell
curl.exe -X POST "http://127.0.0.1:8765/observer/pause?paused=true"
```

Pausing is recorded in the events table, so the timeline shows a deliberate gap
rather than an unexplained one.
