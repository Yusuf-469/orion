"""Experience memory: the step sequences that worked, reused as a hint on similar goals.

Idea from Agent-S (Simular, Apache-2.0): agents get better when they recall how a similar task was done
before. ORION keeps only its own verified successes (the run finished with every listed step ok at least
once), stores the tool sequence with short arguments, never page or document text, and redacts secrets
from the goal. The hint is advice for the planner; every action still goes through policy and tools.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from orion.observability import redact

MIN_SIMILARITY = 0.5
KEEP = 500
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "my", "me", "it", "then", "at", "is"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def _brief(tool: str, args: dict[str, Any]) -> str:
    keep = {k: (v if not isinstance(v, str) else v[:40]) for k, v in args.items()
            if k in ("app", "url", "query", "keys", "expression", "path", "out_path") and v}
    return tool + (json.dumps(keep, ensure_ascii=False) if keep else "")


class Experience:
    def __init__(self, db: Path | str):
        self.db = Path(db)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS experience (id INTEGER PRIMARY KEY, goal TEXT NOT NULL, "
                      "steps TEXT NOT NULL, created REAL NOT NULL)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db, timeout=5)

    def record(self, goal: str, steps: list) -> bool:
        """Save the successful steps of a finished run (Step objects with .tool/.args/.ok). Returns True if saved."""
        seq: list[str] = []
        for s in steps:
            if s.ok and s.tool not in ("ask_user", "finish"):
                b = _brief(s.tool, s.args)
                if not seq or seq[-1] != b:
                    seq.append(b)
        if not seq:
            return False
        with self._conn() as c:
            c.execute("INSERT INTO experience (goal, steps, created) VALUES (?, ?, ?)",
                      (redact(goal)[:500], json.dumps(seq[:15]), time.time()))
            c.execute("DELETE FROM experience WHERE id NOT IN (SELECT id FROM experience ORDER BY id DESC LIMIT ?)",
                      (KEEP,))
        return True

    def recall(self, goal: str) -> tuple[str, list[str], float] | None:
        """(past goal, its steps, similarity) of the most similar past success, or None."""
        with self._conn() as c:
            rows = c.execute("SELECT goal, steps FROM experience ORDER BY id DESC LIMIT ?", (KEEP,)).fetchall()
        best = max(((similarity(goal, g), g, s) for g, s in rows), default=None)
        if best is None or best[0] < MIN_SIMILARITY:
            return None
        return best[1], json.loads(best[2]), round(best[0], 2)
