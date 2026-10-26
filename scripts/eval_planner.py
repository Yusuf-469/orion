"""Evaluate a planner on the frozen prompt set (C4 metrics).

usage: python scripts/eval_planner.py [--prompts research/planner_eval/prompts_v1.json] [--out FILE]

Uses all permissions so the measurement is about planning, not policy, and a
throwaway workspace path (nothing is executed). Only the template planner is
available until a local LLM backend is installed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from orion.app.main_window import build_registry
from orion.planner.service import plan_request
from orion.planner.template import TemplatePlanner
from orion.policy import PolicyEngine
from orion.tools import Permission


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default="research/planner_eval/prompts_v1.json")
    ap.add_argument("--out")
    a = ap.parse_args()
    data = json.loads(Path(a.prompts).read_text(encoding="utf-8"))
    reg, pol = build_registry(), PolicyEngine(frozenset(Permission))
    planner = TemplatePlanner()
    rows, confusion = [], Counter()
    with tempfile.TemporaryDirectory() as ws:
        for p in data["prompts"]:
            r = plan_request(planner, p["text"], reg, pol, Path(ws))
            invalid_calls = sum(i.code in ("unknown_tool", "invalid_args") for i in r.issues)
            rows.append({"id": p["id"], "expect": p["expect"], "got": r.status, "invalid_tool_calls": invalid_calls,
                         "steps": len(r.plan.steps) if r.plan else 0})
            confusion[(p["expect"], r.status)] += 1
    n = len(rows)
    correct = sum(r["expect"] == r["got"] for r in rows)
    proposed = [r for r in rows if r["got"] in ("ok", "invalid")]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = {
        "planner": planner.name, "prompt_set": data["version"], "n": n, "git_commit": commit,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "behaviour_accuracy": f"{correct}/{n}",
        "plan_validation_rate": f"{sum(r['got'] == 'ok' for r in proposed)}/{len(proposed)} of proposed plans",
        "invalid_tool_calls": sum(r["invalid_tool_calls"] for r in rows),
        "confusion": {f"{e}->{g}": c for (e, g), c in sorted(confusion.items())},
        "mismatches": [r for r in rows if r["expect"] != r["got"]],
    }
    text = json.dumps(report, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
