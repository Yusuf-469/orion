"""SQLite persistence for tasks, steps and events.

One connection guarded by a lock, so the UI thread and the runner thread can
both use the store. Every status change goes through `check_transition` inside
a transaction; an illegal transition raises and writes nothing.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from orion.observability.logging import redact
from orion.orchestration.states import Status, check_transition

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    idx INTEGER NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL,
    ended_at REAL,
    evidence TEXT,
    UNIQUE (task_id, idx)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_task ON steps(task_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
"""


class TaskStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- tasks -------------------------------------------------------------

    def create_task(self, title: str, dry_run: bool) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO tasks(title, status, dry_run, created_at, updated_at) VALUES (?,?,?,?,?)",
                (title, Status.PENDING, int(dry_run), now, now),
            )
            return int(cur.lastrowid)

    def set_task_status(self, task_id: int, new: Status, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    raise KeyError(f"task {task_id} not found")
                check_transition(Status(row["status"]), new)
                self._conn.execute(
                    "UPDATE tasks SET status=?, updated_at=?, error=COALESCE(?, error) WHERE id=?",
                    (new, time.time(), redact(error) if error else None, task_id),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def get_task(self, task_id: int) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"task {task_id} not found")
        return dict(row)

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # --- steps -------------------------------------------------------------

    def add_step(self, task_id: int, idx: int, name: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO steps(task_id, idx, name, status) VALUES (?,?,?,?)",
                (task_id, idx, name, Status.PENDING),
            )
            return int(cur.lastrowid)

    def set_step_status(self, step_id: int, new: Status, evidence: str | None = None) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT status FROM steps WHERE id=?", (step_id,)).fetchone()
                if row is None:
                    raise KeyError(f"step {step_id} not found")
                check_transition(Status(row["status"]), new)
                self._conn.execute(
                    """UPDATE steps SET status=?,
                         started_at = CASE WHEN ?='running' THEN ? ELSE started_at END,
                         ended_at = CASE WHEN ? IN ('succeeded','failed','cancelled','skipped') THEN ? ELSE ended_at END,
                         evidence = COALESCE(?, evidence)
                       WHERE id=?""",
                    (new, new, now, new, now, redact(evidence) if evidence else None, step_id),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def list_steps(self, task_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM steps WHERE task_id=? ORDER BY idx", (task_id,)).fetchall()
        return [dict(r) for r in rows]

    # --- events ------------------------------------------------------------

    def add_event(self, task_id: int | None, level: str, kind: str, message: str,
                  data: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(task_id, ts, level, kind, message, data) VALUES (?,?,?,?,?,?)",
                (task_id, time.time(), level, kind, redact(message),
                 json.dumps(redact(data), default=str) if data is not None else None),
            )

    def list_events(self, task_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        return [dict(r) for r in rows]
