"""The pre-registered P1-vs-P0 selection rule, applied as written (it was skipped in v1; see grounding_v1.md).

Rule (CLAUDE.md, fixed before training): P1 ships only if it beats P0 on VALIDATION, with the paired
bootstrap 95% CI on the accuracy difference excluding 0; otherwise P0 ships and P1 is a negative result.
Uses the already-trained models and their own operating points; no retraining, no test-set use for the
decision (test numbers are printed for reference only).

usage: python research/training/select_p1.py --data research/data_collection/out/v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib

sys.path.insert(0, str(Path(__file__).parent))
import train_grounding as tg  # noqa: E402


def per_instance(bundle: dict, samples: list, sims: dict | None) -> tuple[list[bool], list[bool]]:
    tg.VIS = sims
    cache = tg.best_scores(bundle["model"], samples)
    r = tg.evaluate("x", samples, tg.learned(cache, bundle["tau"], bundle.get("margin", 0.0)))
    correct = r["_per"]
    wrong = []
    for s, ins, tb, merged in tg.examples(samples):
        p, c, p2 = cache.get((s["sample_id"], ins["text"]), (0.0, None, 0.0))
        pick = c if (p >= bundle["tau"] and p - p2 >= bundle.get("margin", 0.0)) else None
        wrong.append(tg.outcome(pick, tb) == "wrong_click")
    return correct, wrong


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--p0", default="artifacts/models/grounding_p0.joblib")
    ap.add_argument("--p0v", default="artifacts/models/grounding_p0v_candidate.joblib")
    ap.add_argument("--p1", default="artifacts/models/grounding_p1_candidate.joblib")
    ap.add_argument("--report", default="research/reports/grounding_p1_selection_v1.json")
    a = ap.parse_args()
    data = Path(a.data)
    samples = [json.loads(l) for l in (data / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    rest = [s for s in samples if s["family"] not in tg.TEST_FAMILIES]
    val = [s for s in rest if s["seed"] % 5 == 0]
    test = [s for s in samples if s["family"] in tg.TEST_FAMILIES]
    models = {"P0": (joblib.load(a.p0), None),
              "P0+frozen SigLIP": (joblib.load(a.p0v), joblib.load(data / "siglip_sims.joblib")),
              "P1 fine-tuned SigLIP": (joblib.load(a.p1), joblib.load(data / "siglip_ft_sims.joblib"))}
    for name, (b, sims) in models.items():
        assert bool(b.get("visual")) == (sims is not None), f"{name}: model/visual-input mismatch"
    out: dict = {"rule": "P1 ships iff validation paired-bootstrap 95% CI of accuracy(P1) - accuracy(P0) excludes 0 "
                         "(and is positive)", "models": {}, "comparisons": {}}
    per = {}
    for split, ss in (("val", val), ("test", test)):
        for name, (b, sims) in models.items():
            c, w = per_instance(b, ss, sims)
            per[(split, name)] = (c, w)
            out["models"].setdefault(name, {})[split] = {"n": len(c), "accuracy": round(sum(c) / len(c), 4),
                                                          "wrong_click_rate": round(sum(w) / len(w), 4)}
    for split in ("val", "test"):
        for other in ("P0", "P0+frozen SigLIP"):
            c1, w1 = per[(split, "P1 fine-tuned SigLIP")]
            c0, w0 = per[(split, other)]
            out["comparisons"][f"{split}: P1 - {other}"] = {
                "accuracy_diff": round(sum(c1) / len(c1) - sum(c0) / len(c0), 4),
                "accuracy_diff_95ci": tg.bootstrap_diff(c1, c0),
                "wrong_click_diff": round(sum(w1) / len(w1) - sum(w0) / len(w0), 4),
                "wrong_click_diff_95ci": tg.bootstrap_diff(w1, w0)}
    lo, hi = out["comparisons"]["val: P1 - P0"]["accuracy_diff_95ci"]
    out["decision_by_rule"] = "P1 passes the rule" if lo > 0 else "P1 fails the rule; P0 ships"
    Path(a.report).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
