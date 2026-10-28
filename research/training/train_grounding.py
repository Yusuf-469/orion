"""Train the learned grounding scorer (P0) and compare it with the rule-based locators.

Data: rendered synthetic pages (render_synth.py). Families 'sidebar_nav' and 'wizard' are HELD OUT
for the final test (never used for training or tuning). Validation = every 5th seed of the
training families, used only to pick the abstain threshold.

An answer is correct if ORION clicks inside the right element, or abstains when the right answer
is to abstain (hidden / missing / ambiguous target). A wrong click is the costly error.

usage: python research/training/train_grounding.py --data research/data_collection/out/v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from orion.grounding.features import FEATURES, featurize
from orion.grounding.locate import Candidate, locate, merge
from orion.grounding.screen import Box, OcrWord

TEST_FAMILIES = {"sidebar_nav", "wizard"}
W, H = 1280, 800


def candidates(sample: dict, use_meta=True, use_ocr=True) -> list[Candidate]:
    meta = [Candidate(m["text"], Box(*m["box"]), "uia", m["role"], 1.0, True, m["disabled"])
            for m in sample["metadata"]] if use_meta else []
    ocr = [OcrWord(w["text"], Box(*w["box"]), w["conf"]) for w in sample["ocr"]] if use_ocr else []
    return merge(meta, ocr)


def hit(c: Candidate | None, target_box: list | None) -> bool:
    if c is None or target_box is None:
        return False
    x, y = c.box.center
    return target_box[0] <= x <= target_box[2] and target_box[1] <= y <= target_box[3]


def examples(samples: list[dict]):
    for s in samples:
        merged = candidates(s)
        for ins in s["instructions"]:
            tb = s["boxes"].get(ins["target_id"]) if ins["target_id"] else None
            yield s, ins, tb, merged


def outcome(pick: Candidate | None, tb) -> str:
    if tb is None:
        return "correct" if pick is None else "wrong_click"
    if pick is None:
        return "missed"
    return "correct" if hit(pick, tb) else "wrong_click"


def evaluate(name: str, samples, chooser) -> dict:
    counts = {"correct": 0, "wrong_click": 0, "missed": 0}
    per = []
    for s, ins, tb, merged in examples(samples):
        o = outcome(chooser(s, ins, merged), tb)
        counts[o] += 1
        per.append(o == "correct")
    n = sum(counts.values())
    return {"method": name, "n": n, "accuracy": round(counts["correct"] / n, 4),
            "wrong_click_rate": round(counts["wrong_click"] / n, 4),
            "missed_rate": round(counts["missed"] / n, 4), "_per": per}


def rule(use_meta, use_ocr):
    def choose(s, ins, merged):
        cands = merged if (use_meta and use_ocr) else candidates(s, use_meta, use_ocr)
        return locate(ins["text"], cands).candidate
    return choose


def best_scores(model, samples) -> dict:
    """(sample_id, instruction) -> (best probability, best candidate). One batched predict per page."""
    out = {}
    for s in samples:
        merged = candidates(s)
        if not merged:
            continue
        blocks = [featurize(ins["text"], merged, W, H) for ins in s["instructions"]]
        probs = model.predict_proba(np.array([r for b in blocks for r in b]))[:, 1]
        for k, ins in enumerate(s["instructions"]):
            p = probs[k * len(merged):(k + 1) * len(merged)]
            i = int(p.argmax())
            out[(s["sample_id"], ins["text"])] = (float(p[i]), merged[i])
    return out


def learned(cache: dict, tau: float):
    def choose(s, ins, merged):
        p, c = cache.get((s["sample_id"], ins["text"]), (0.0, None))
        return c if p >= tau else None
    return choose


def bootstrap_diff(a: list[bool], b: list[bool], reps=2000, seed=0) -> tuple[float, float]:
    rng = random.Random(seed)
    n, d = len(a), []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        d.append(sum(a[i] for i in idx) / n - sum(b[i] for i in idx) / n)
    d.sort()
    return round(d[int(0.025 * reps)], 4), round(d[int(0.975 * reps)], 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model-out", default="artifacts/models/grounding_p0.joblib")
    ap.add_argument("--report", default="research/reports/grounding_p0_v1.json")
    a = ap.parse_args()
    raw = Path(a.data, "samples.jsonl").read_bytes()
    samples = [json.loads(l) for l in raw.decode("utf-8").splitlines()]
    test = [s for s in samples if s["family"] in TEST_FAMILIES]
    rest = [s for s in samples if s["family"] not in TEST_FAMILIES]
    val = [s for s in rest if s["seed"] % 5 == 0]
    train = [s for s in rest if s["seed"] % 5 != 0]

    X, y = [], []
    for s, ins, tb, merged in examples(train):
        for c, row in zip(merged, featurize(ins["text"], merged, W, H)):
            X.append(row)
            y.append(int(hit(c, tb)))
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0)
    model.fit(np.array(X), np.array(y))

    # Abstain threshold from validation only: reward correct answers, punish wrong clicks 3x.
    val_cache, test_cache = best_scores(model, val), best_scores(model, test)
    best_tau, best_val = 0.5, -1e9
    for tau in [i / 100 for i in range(20, 96, 2)]:
        r = evaluate("p0", val, learned(val_cache, tau))
        v = r["accuracy"] - 3 * r["wrong_click_rate"]
        if v > best_val:
            best_tau, best_val = tau, v

    rules = [("B1 metadata only (rules)", rule(True, False)), ("B2 OCR only (rules)", rule(False, True)),
             ("B4 metadata + OCR (rules, current)", rule(True, True))]
    results = {"val": [evaluate(n, val, f) for n, f in rules] + [evaluate("P0 learned scorer", val,
                                                                         learned(val_cache, best_tau))],
               "test": [evaluate(n, test, f) for n, f in rules] + [evaluate("P0 learned scorer", test,
                                                                           learned(test_cache, best_tau))]}
    lo, hi = bootstrap_diff(results["test"][3]["_per"], results["test"][2]["_per"])
    for split in results.values():
        for r in split:
            r.pop("_per")

    Path(a.model_out).parent.mkdir(parents=True, exist_ok=True)
    data_hash = hashlib.sha256(raw).hexdigest()[:16]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    joblib.dump({"model": model, "tau": best_tau, "features": FEATURES, "data_sha256": data_hash,
                 "commit": commit}, a.model_out)
    report = {"data": a.data, "data_sha256_16": data_hash, "git_commit": commit,
              "pages": {"train": len(train), "val": len(val), "test_heldout_families": len(test)},
              "test_families": sorted(TEST_FAMILIES), "train_rows": len(y), "positives": int(sum(y)),
              "abstain_threshold": best_tau, "results": results,
              "test_accuracy_gain_P0_vs_B4_95ci": [lo, hi]}
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for r in results["test"]:
        print(f"TEST {r['method']:<36} correct {r['accuracy']:.1%}  wrong clicks {r['wrong_click_rate']:.1%}  "
              f"missed {r['missed_rate']:.1%}  (n={r['n']})")
    print(f"P0 - B4 accuracy on held-out families: 95% CI [{lo:+.1%}, {hi:+.1%}]; abstain threshold {best_tau}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
