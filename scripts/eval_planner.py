"""Evaluate a planner on the frozen prompt set (C4 metrics).

usage:
  python scripts/eval_planner.py --planner template [--out FILE]
  python scripts/eval_planner.py --planner llm --model phi3.5 [--constrained] [--num-ctx 4096] [--out FILE]

Uses all permissions so the measurement is about planning, not policy, and a
throwaway workspace path (nothing is executed).

Metrics per run:
  behaviour_accuracy  strict: got == expected status (ok / clarify / unsupported / invalid)
  safe_rate           a prompt that must not produce a runnable plan (clarify/unsupported/invalid) did not
                      produce one, i.e. got != "ok"
  plan_validation     share of produced plans that pass the validator
  reference_match     for prompts expected "ok": the plan matches the template planner's reference plan
                      ("exact" = same tools in order and same literal args after path normalization;
                       "tools" = same tools in order only)
  invalid_tool_calls  unknown tool or bad args, summed over all attempts (incl. repaired ones)
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from orion.app.main_window import build_registry
from orion.planner.service import plan_request
from orion.planner.template import TemplatePlanner
from orion.planner.validator import topo_order
from orion.policy import PolicyEngine
from orion.tools import Permission

PATH_KEYS = ("path", "src", "dst")


def _norm_args(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        if k in PATH_KEYS and isinstance(v, str):
            v = PureWindowsPath(v).as_posix().strip("/").lower()
        out[k] = v
    return out


def signature(plan) -> list[tuple[str, dict]]:
    by_id = {s.id: s for s in plan.steps}
    return [(by_id[i].tool_id, _norm_args(by_id[i].args)) for i in (topo_order(plan) or [])]


def compare(plan, ref) -> str:
    a, b = signature(plan), signature(ref)
    if [t for t, _ in a] != [t for t, _ in b]:
        return "none"
    # References like ${s1.text} differ by step id between planners; compare only literal args.
    lit = lambda d: {k: v for k, v in d.items() if not (isinstance(v, str) and v.startswith("${"))}  # noqa: E731
    return "exact" if all(lit(x) == lit(y) for (_, x), (_, y) in zip(a, b)) else "tools"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default="research/planner_eval/prompts_v1.json")
    ap.add_argument("--planner", choices=["template", "llm"], default="template")
    ap.add_argument("--model", default="phi3.5")
    ap.add_argument("--constrained", action="store_true")
    ap.add_argument("--num-ctx", type=int, default=4096)
    ap.add_argument("--max-repairs", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()
    data = json.loads(Path(a.prompts).read_text(encoding="utf-8"))
    reg, pol = build_registry(), PolicyEngine(frozenset(Permission))
    template = TemplatePlanner()
    backend = None
    rows, confusion = [], Counter()
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        if a.planner == "llm":
            from orion.models.ollama import OllamaBackend
            from orion.planner.llm import LLMPlanner, output_schema
            backend = OllamaBackend(model=a.model, schema=output_schema() if a.constrained else None,
                                    num_ctx=a.num_ctx)
            planner = LLMPlanner(backend, reg, pol, ws, max_repairs=a.max_repairs)
        else:
            planner = template
        for p in data["prompts"]:
            n_calls = len(backend.calls) if backend else 0
            t0 = time.monotonic()
            r = plan_request(planner, p["text"], reg, pol, ws)
            secs = time.monotonic() - t0
            row = {"id": p["id"], "expect": p["expect"], "got": r.status, "seconds": round(secs, 2),
                   "metrics": r.metrics, "invalid_tool_calls": r.metrics.get("invalid_tool_calls", 0) +
                   sum(i.code in ("unknown_tool", "invalid_args") for i in r.issues if r.status == "invalid"
                       and a.planner == "template")}
            if r.plan is not None:
                row["plan"] = [(t, args) for t, args in signature(r.plan)]
            if p["expect"] == "ok":
                ref = plan_request(template, p["text"], reg, pol, ws)
                row["reference_match"] = compare(r.plan, ref.plan) if (r.status == "ok" and ref.plan) else "none"
            if backend:
                row["llm_calls"] = backend.calls[n_calls:]
            rows.append(row)
            confusion[(p["expect"], r.status)] += 1
            print(f"{p['id']} expect={p['expect']:<11} got={r.status:<11} "
                  f"{row.get('reference_match', ''):<5} {secs:6.1f}s", flush=True)

    n = len(rows)
    produced = [r for r in rows if r["got"] in ("ok", "invalid")]
    must_not_run = [r for r in rows if r["expect"] != "ok"]
    should_run = [r for r in rows if r["expect"] == "ok"]
    lat = [r["seconds"] for r in rows]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "src", "scripts"], capture_output=True,
                                text=True).stdout.strip())
    report = {
        "planner": a.planner, "model": a.model if a.planner == "llm" else None,
        "constrained_decoding": a.constrained if a.planner == "llm" else None,
        "num_ctx": a.num_ctx if a.planner == "llm" else None, "max_repairs": a.max_repairs,
        "decoding": "temperature 0, seed 0" if a.planner == "llm" else "deterministic",
        "prompt_set": data["version"], "n": n, "git_commit": commit, "src_dirty": dirty,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "behaviour_accuracy": f"{sum(r['expect'] == r['got'] for r in rows)}/{n}",
        "safe_rate": f"{sum(r['got'] != 'ok' for r in must_not_run)}/{len(must_not_run)}",
        "plan_validation": f"{sum(r['got'] == 'ok' for r in produced)}/{len(produced)}",
        "reference_match_exact": f"{sum(r.get('reference_match') == 'exact' for r in should_run)}/{len(should_run)}",
        "reference_match_tools_or_better": f"{sum(r.get('reference_match') in ('exact', 'tools') for r in should_run)}"
                                           f"/{len(should_run)}",
        "invalid_tool_calls": sum(r["invalid_tool_calls"] for r in rows),
        "latency_s": {"median": round(statistics.median(lat), 2), "max": round(max(lat), 2),
                      "total": round(sum(lat), 1)},
        "confusion": {f"{e}->{g}": c for (e, g), c in sorted(confusion.items())},
        "rows": rows,
    }
    summary = {k: v for k, v in report.items() if k != "rows"}
    print(json.dumps(summary, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
