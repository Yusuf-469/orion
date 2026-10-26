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

SCHEMA_VERSION = 2

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

# v2 (Stage 3): plans, checkpoints, per-step tool data, task outcome.
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS plans (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
    planner TEXT NOT NULL,
    goal_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    ts REAL NOT NULL,
    label TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
"""
_V2_COLUMNS = {
    "steps": [("step_key", "TEXT"), ("tool_id", "TEXT"), ("args_json", "TEXT"), ("output_json", "TEXT"),
              ("action_id", "TEXT")],
    "tasks": [("outcome", "TEXT")],
}


def _backup_if_old(path: Path) -> None:
    """Before migrating an older database, keep a copy next to it (orion.db.v1.bak)."""
    if not path.is_file():
        return
    con = sqlite3.connect(str(path))
    try:
        row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError:
        row = None
    finally:
        con.close()
    if row is None or int(row[0]) >= SCHEMA_VERSION:
        return
    backup = path.with_name(f"{path.name}.v{row[0]}.bak")
    if not backup.exists():
        src, dst = sqlite3.connect(str(path)), sqlite3.connect(str(backup))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()


class TaskStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            _backup_if_old(Path(path))
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Bring any older database up to SCHEMA_VERSION in place, keeping history."""
        self._conn.executescript(_SCHEMA_V2)
        for table, cols in _V2_COLUMNS.items():
            have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))

    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])

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

    # --- plans, plan steps, checkpoints (v2) ---------------------------------

    def save_plan(self, task_id: int, planner: str, goal_json: str, plan_json: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO plans(task_id, planner, goal_json, plan_json, created_at) VALUES (?,?,?,?,?)",
                (task_id, planner, redact(goal_json), redact(plan_json), time.time()))

    def load_plan(self, task_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM plans WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def add_plan_step(self, task_id: int, idx: int, step_key: str, name: str, tool_id: str,
                      args: dict[str, Any]) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO steps(task_id, idx, name, status, step_key, tool_id, args_json) VALUES (?,?,?,?,?,?,?)",
                (task_id, idx, name, Status.PENDING, step_key, tool_id, json.dumps(args)))
            return int(cur.lastrowid)

    def mark_step_started(self, step_id: int, action_id: str) -> None:
        """READY -> RUNNING and record the action id in ONE transaction (the crash marker)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT status FROM steps WHERE id=?", (step_id,)).fetchone()
                check_transition(Status(row["status"]), Status.RUNNING)
                self._conn.execute("UPDATE steps SET status=?, started_at=?, action_id=? WHERE id=?",
                                   (Status.RUNNING, time.time(), action_id, step_id))
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def set_step_output(self, step_id: int, output: dict[str, Any] | None) -> None:
        with self._lock:
            self._conn.execute("UPDATE steps SET output_json=? WHERE id=?",
                               (json.dumps(output, default=str) if output is not None else None, step_id))

    def set_task_outcome(self, task_id: int, outcome: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tasks SET outcome=?, updated_at=? WHERE id=?", (outcome, time.time(), task_id))

    def save_checkpoint(self, task_id: int, label: str) -> None:
        with self._lock:
            snap = json.dumps({r["step_key"] or str(r["idx"]): r["status"] for r in self._conn.execute(
                "SELECT idx, step_key, status FROM steps WHERE task_id=? ORDER BY idx", (task_id,))})
            self._conn.execute("INSERT INTO checkpoints(task_id, ts, label, snapshot) VALUES (?,?,?,?)",
                               (task_id, time.time(), label, snap))

    def list_checkpoints(self, task_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM checkpoints WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        return [dict(r) for r in rows]

    def interrupted_tasks(self) -> list[dict[str, Any]]:
        """Tasks that were mid-run when ORION stopped (crash, kill, power loss)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status IN ('ready','running') ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # --- history controls (spec 10) ------------------------------------------

    def delete_task(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for table in ("events", "steps", "checkpoints", "plans"):
                    self._conn.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
                self._conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def delete_all_history(self) -> int:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for table in ("events", "steps", "checkpoints", "plans", "tasks"):
                    self._conn.execute(f"DELETE FROM {table}")
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("VACUUM")
            return int(n)
