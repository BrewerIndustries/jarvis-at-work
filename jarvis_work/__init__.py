"""Jarvis at Work — Windows work-machine assistant.

Three processes, deliberately separate:

  daemon/     long-lived. Owns the SQLite store, runs the observer loop,
              talks to the agent bridge. Binds 127.0.0.1 only.
  mcp/        short-lived, spawned and killed by Claude Desktop at will.
              A thin stdio shim that forwards to the daemon over localhost —
              it holds no state, because it does not survive long enough to.
  agent/      runs on the Hyper-V VM, not on this machine. Drives the second
              Claude Desktop through Windows UI Automation.
"""

__version__ = "0.1.0"
