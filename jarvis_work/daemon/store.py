"""SQLite store. Four tables, all local, never leaves the machine.

  snapshots   — what was on screen, one row per observer tick
  work_items  — the registry the "handler" routes into
  memory      — durable facts, the thing that makes a fresh Claude chat cheap
  events      — an append-only audit log of everything the agent did
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    app         TEXT    NOT NULL,
    title       TEXT    NOT NULL DEFAULT '',
    idle_secs   REAL    NOT NULL DEFAULT 0,
    locked      INTEGER NOT NULL DEFAULT 0,
    extra       TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts);

CREATE TABLE IF NOT EXISTS work_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts  REAL    NOT NULL,
    updated_ts  REAL    NOT NULL,
    title       TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'open',
    project     TEXT    NOT NULL DEFAULT '',
    source      TEXT    NOT NULL DEFAULT 'manual',
    context     TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_work_status ON work_items(status);

CREATE TABLE IF NOT EXISTS memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts  REAL    NOT NULL,
    fact        TEXT    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '',
    source      TEXT    NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    kind        TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── snapshots ────────────────────────────────────────────────────────────
    def add_snapshot(self, app: str, title: str = "", idle_secs: float = 0.0,
                     locked: bool = False, extra: dict | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO snapshots (ts, app, title, idle_secs, locked, extra) VALUES (?,?,?,?,?,?)",
            (time.time(), app, title, idle_secs, int(locked), json.dumps(extra or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def current_snapshot(self) -> dict | None:
        row = self._conn.execute("SELECT * FROM snapshots ORDER BY ts DESC LIMIT 1").fetchone()
        return _row(row)

    def timeline(self, since_ts: float, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE ts >= ? ORDER BY ts ASC LIMIT ?", (since_ts, limit)
        ).fetchall()
        return [_row(r) for r in rows]

    def prune_snapshots(self, older_than_ts: float) -> int:
        cur = self._conn.execute("DELETE FROM snapshots WHERE ts < ?", (older_than_ts,))
        self._conn.commit()
        return cur.rowcount

    # ── work items ───────────────────────────────────────────────────────────
    def add_work_item(self, title: str, detail: str = "", project: str = "",
                      source: str = "manual", context: dict | None = None) -> int:
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO work_items (created_ts, updated_ts, title, detail, status, project, source, context)"
            " VALUES (?,?,?,?,'open',?,?,?)",
            (now, now, title, detail, project, source, json.dumps(context or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_work_items(self, status: str | None = "open", limit: int = 100) -> list[dict]:
        if status and status != "all":
            rows = self._conn.execute(
                "SELECT * FROM work_items WHERE status = ? ORDER BY updated_ts DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM work_items ORDER BY updated_ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row(r) for r in rows]

    def update_work_item(self, item_id: int, status: str | None = None,
                         note: str | None = None, project: str | None = None) -> dict | None:
        row = self._conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        detail = row["detail"]
        if note:
            stamp = time.strftime("%Y-%m-%d %H:%M")
            detail = f"{detail}\n[{stamp}] {note}".strip()
        self._conn.execute(
            "UPDATE work_items SET status = ?, detail = ?, project = ?, updated_ts = ? WHERE id = ?",
            (status or row["status"], detail, project if project is not None else row["project"],
             time.time(), item_id),
        )
        self._conn.commit()
        return _row(self._conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone())

    # ── memory ───────────────────────────────────────────────────────────────
    def add_memory(self, fact: str, tags: str = "", source: str = "manual") -> int:
        cur = self._conn.execute(
            "INSERT INTO memory (created_ts, fact, tags, source) VALUES (?,?,?,?)",
            (time.time(), fact, tags, source),
        )
        self._conn.commit()
        return cur.lastrowid

    def search_memory(self, query: str, limit: int = 20) -> list[dict]:
        """Substring match over fact + tags.

        Deliberately dumb for v1. The interesting version is embeddings, but a
        LIKE scan over a few thousand rows is instant and gives us something to
        measure the smarter version against.
        """
        like = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM memory WHERE fact LIKE ? OR tags LIKE ? ORDER BY created_ts DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def recent_memory(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM memory ORDER BY created_ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row(r) for r in rows]

    # ── events ───────────────────────────────────────────────────────────────
    def add_event(self, kind: str, detail: dict | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO events (ts, kind, detail) VALUES (?,?,?)",
            (time.time(), kind, json.dumps(detail or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def recent_events(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row(r) for r in rows]


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("extra", "context", "detail"):
        if k in d and isinstance(d[k], str) and d[k].startswith("{"):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d
