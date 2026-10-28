"""Run the ORION benchmark and write raw runs + a summary.

usage: python -m benchmark.run_benchmark [--runs 3] [--only ID_PREFIX ...] [--conditions C3 C2 C1 A_norec]
Output: benchmark/results/<run_id>/{runs.jsonl, summary.json, summary.md}

Matrix: C3 on every task; C2 on tasks whose result depends on grounding; C1 on single-goal tasks;
A_norec on failure-and-recovery tasks. Needs the PC left alone (real tasks use the mouse and keyboard).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from benchmark.harness import ROOT, TASKS, Task, monitors, run_once

COND_NAMES = {"C3": "ORION (full)", "C2": "ORION without learned grounding (rules)",
              "C1": "fixed script (no planner/verify/recover)", "A_norec": "ORION without recovery"}


def applies(task: Task, cond: str) -> bool:
    return {"C3": True, "C2": task.grounding, "C1": task.custom is None and task.expect != "ask",
            "A_norec": task.failure}[cond]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(rows: list[dict], key=lambda r: r["passed"]) -> dict:
    k, n = sum(1 for r in rows if key(r)), len(rows)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


class PeakRSS(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        import psutil
        self.proc, self.peak, self.cpu, self.stop = psutil.Process(), 0, [], threading.Event()

    def run(self):
        self.proc.cpu_percent(None)
        while not self.stop.wait(0.5):
            self.peak = max(self.peak, self.proc.memory_info().rss)
            self.cpu.append(self.proc.cpu_percent(None))


def environment() -> dict:
    model = ROOT / "artifacts" / "models" / "grounding_p0.joblib"
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa
    return {
        "git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
        "python": sys.version.split()[0], "os": platform.platform(), "machine": platform.processor(),
        "monitors": monitors(),
        "grounding_model": {"path": str(model.relative_to(ROOT)), "exists": model.exists(),
                            "bytes": model.stat().st_size if model.exists() else 0,
                            "sha256": hashlib.sha256(model.read_bytes()).hexdigest()[:16] if model.exists() else None},
        "planner": "template", "llm": "not used in this benchmark",
    }


def summarize(rows: list[dict], env: dict, res: dict) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[r["condition"]].append(r)
    s: dict = {"environment": env, "resources": res, "conditions": {}}
    for cond, rs in by.items():
        cats = defaultdict(list)
        for r in rs:
            cats[r["category"]].append(r)
        lat = sorted(r["latency_s"] for r in rs)
        c = {"name": COND_NAMES[cond], "success": rate(rs), "by_category": {k: rate(v) for k, v in sorted(cats.items())},
             "safety_violations": sum(r["violation"] for r in rs),
             "runs_with_question": rate(rs, lambda r: bool(r["asked"])),
             "harness_errors": sum(bool(r["error"]) for r in rs),
             "latency_s": {"median": round(statistics.median(lat), 2) if lat else None,
                           "p95": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2) if lat else None}}
        ground = [r for r in rs if TASK[r["task"]].grounding]
        if ground:
            c["grounding"] = {"correct": rate(ground), "wrong_click_runs": sum(r["violation"] for r in ground)}
        fail = [r for r in rs if TASK[r["task"]].failure]
        if fail:
            c["failure_recovery"] = rate(fail)
        # Failure detection: does ORION's own outcome say "not done" exactly when the checker says so?
        goal = [r for r in rs if r["orion_outcome"] and r["orion_outcome"] != "script_finished"
                and TASK[r["task"]].expect == "complete"]
        if goal:
            tp = sum(1 for r in goal if not r["passed"] and r["orion_outcome"] != "verified_complete")
            fp = sum(1 for r in goal if r["passed"] and r["orion_outcome"] != "verified_complete")
            fn = sum(1 for r in goal if not r["passed"] and r["orion_outcome"] == "verified_complete")
            c["failure_detection"] = {"actual_failures": tp + fn, "flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn,
                                      "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                                      "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                                      "false_success_claims": fn}
        s["conditions"][cond] = c
    per_task = defaultdict(dict)
    for r in rows:
        per_task[r["task"]].setdefault(r["condition"], []).append(r["passed"])
    s["per_task"] = {t: {c: f"{sum(v)}/{len(v)}" for c, v in d.items()} for t, d in per_task.items()}
    return s


def markdown(s: dict, run_id: str, runs: int) -> str:
    e, conds = s["environment"], s["conditions"]
    pct = lambda x: f"{100 * x['rate']:.0f}% ({x['k']}/{x['n']}; CI {100 * x['ci95'][0]:.0f}-{100 * x['ci95'][1]:.0f})"  # noqa
    out = [f"# ORION benchmark {run_id}", "",
           f"Commit `{e['git_commit'][:10]}`{' (dirty)' if e['git_dirty'] else ''}, {e['os']}, Python {e['python']}, "
           f"{len(e['monitors'])} monitors, grounding model sha256 {e['grounding_model']['sha256']}. "
           f"{runs} runs per task per condition. Scored by independent checks (files, click log, form state).", "",
           "| Condition | Success | Safety violations | Runs with a question | Median / p95 latency |",
           "|---|---|---|---|---|"]
    for k in ("C3", "C2", "C1", "A_norec"):
        if k in conds:
            c = conds[k]
            out.append(f"| {k} {c['name']} | {pct(c['success'])} | {c['safety_violations']} | "
                       f"{pct(c['runs_with_question'])} | {c['latency_s']['median']} s / {c['latency_s']['p95']} s |")
    out += ["", "## By category (success)", "", "| Category | " + " | ".join(k for k in conds) + " |",
            "|---|" + "---|" * len(conds)]
    cats = sorted({c for v in conds.values() for c in v["by_category"]})
    for cat in cats:
        out.append(f"| {cat} | " + " | ".join(pct(conds[k]["by_category"][cat]) if cat in conds[k]["by_category"]
                                                else "n/a" for k in conds) + " |")
    out += ["", "## Grounding, recovery, failure detection", ""]
    for k, c in conds.items():
        bits = []
        if "grounding" in c:
            bits.append(f"grounding correct {pct(c['grounding']['correct'])}, wrong-click runs "
                        f"{c['grounding']['wrong_click_runs']}")
        if "failure_recovery" in c:
            bits.append(f"failure/recovery tasks {pct(c['failure_recovery'])}")
        if "failure_detection" in c:
            fd = c["failure_detection"]
            bits.append(f"failure detection: {fd['actual_failures']} real failures, {fd['tp']} flagged by ORION, "
                        f"{fd['false_success_claims']} false 'complete' claims, {fd['fp']} false alarms")
        out.append(f"- **{k}**: " + "; ".join(bits))
    r = s["resources"]
    out += ["", f"**Resources.** Peak RAM of the agent process {r['peak_rss_mb']} MB, mean CPU {r['mean_cpu_pct']}% "
                f"(of one core), GPU/VRAM: {r['gpu']}, grounding model on disk "
                f"{e['grounding_model']['bytes'] / 1024:.0f} KB.", "", "## Per task (passed/runs)", "",
            "| Task | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds)]
    for t, d in s["per_task"].items():
        out.append(f"| {t} | " + " | ".join(d.get(k, "n/a") for k in conds) + " |")
    return "\n".join(out) + "\n"


TASK = {t.id: t for t in TASKS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--conditions", nargs="*", default=["C3", "C2", "C1", "A_norec"])
    ap.add_argument("--out", default=str(ROOT / "benchmark" / "results"))
    a = ap.parse_args()
    from orion.grounding.screen import ensure_dpi_aware
    ensure_dpi_aware()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = Path(a.out) / run_id
    out.mkdir(parents=True)
    tasks = [t for t in TASKS if not a.only or any(t.id.startswith(p) for p in a.only)]
    plan = [(t, c, i) for i in range(a.runs) for t in tasks for c in a.conditions if applies(t, c)]
    print(f"{len(plan)} runs ({len(tasks)} tasks) -> {out}", flush=True)
    env = environment()
    mon = PeakRSS()
    mon.start()
    rows = []
    with open(out / "runs.jsonl", "w", encoding="utf-8") as f:
        for n, (t, c, i) in enumerate(plan, 1):
            r = run_once(t, c)
            r["run"] = i
            rows.append(r)
            f.write(json.dumps(r) + "\n")
            f.flush()
            mark = "ok " if r["passed"] else "FAIL"
            print(f"[{n}/{len(plan)}] {mark} {c:7} {t.id:40} {r['latency_s']:6.1f}s "
                  f"{'VIOLATION ' if r['violation'] else ''}{r['error'] or ('' if r['passed'] else r['why'])[:90]}",
                  flush=True)
    mon.stop.set()
    res = {"peak_rss_mb": round(mon.peak / 2**20), "mean_cpu_pct": round(statistics.mean(mon.cpu), 1) if mon.cpu
           else None, "gpu": "not used (torch loaded: %s)" % ("torch" in sys.modules)}
    s = summarize(rows, env, res)
    (out / "summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(markdown(s, run_id, a.runs), encoding="utf-8")
    print(markdown(s, run_id, a.runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
