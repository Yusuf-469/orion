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
VIS: dict | None = None   # SigLIP similarities (embed_siglip.py) when --visual is given


def feat(s: dict, text: str, merged: list) -> list[list[float]]:
    rows = featurize(text, merged, W, H)
    if VIS is None:
        return rows
    from orion.grounding.features import add_visual
    from orion.grounding.locate import parse_instruction
    v = VIS.get(f"{s['sample_id']}|{parse_instruction(text)[0] or 'unknown'}")
    return add_visual(rows, list(v) if v is not None else [0.0] * len(merged))


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


def variants(s: dict, ins: dict) -> list[dict]:
    """The generator's phrasing plus the shorter ways people actually ask:
    'the X button' and just 'X'. A shorter phrasing is ambiguous (target None) when another
    visible element shares the label (and role, for 'the X button')."""
    out = [ins]
    if not ins["target_id"]:
        return out
    els = {e["id"]: e for e in s["elements"]}
    t = els[ins["target_id"]]
    visible = [e for e in s["elements"] if not e["hidden"] and e["id"] != t["id"]]
    same_label = [e for e in visible if e["label"] == t["label"]]
    same_role = [e for e in same_label if e["role"] == t["role"]]
    out.append({"text": f"the {t['label']} {t['role']}", "target_id": None if same_role else t["id"],
                "flags": ins["flags"] + (["ambiguous"] if same_role else [])})
    out.append({"text": t["label"], "target_id": None if same_label else t["id"],
                "flags": ins["flags"] + (["ambiguous"] if same_label else [])})
    return out


def examples(samples: list[dict]):
    for s in samples:
        merged = candidates(s)
        for base in s["instructions"]:
            for ins in variants(s, base):
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
    per, wrong_by_flag = [], {}
    for s, ins, tb, merged in examples(samples):
        o = outcome(chooser(s, ins, merged), tb)
        counts[o] += 1
        per.append(o == "correct")
        if o == "wrong_click":
            for f in ins["flags"] or ["plain"]:
                wrong_by_flag[f] = wrong_by_flag.get(f, 0) + 1
    n = sum(counts.values())
    return {"method": name, "n": n, "accuracy": round(counts["correct"] / n, 4),
            "wrong_click_rate": round(counts["wrong_click"] / n, 4),
            "missed_rate": round(counts["missed"] / n, 4), "wrong_clicks_by_case": wrong_by_flag, "_per": per}


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
        all_ins = [v for base in s["instructions"] for v in variants(s, base)]
        blocks = [feat(s, ins["text"], merged) for ins in all_ins]
        probs = model.predict_proba(np.array([r for b in blocks for r in b]))[:, 1]
        for k, ins in enumerate(all_ins):
            p = probs[k * len(merged):(k + 1) * len(merged)]
            order = p.argsort()[::-1]
            i = int(order[0])
            # runner-up = best candidate somewhere else on screen (not overlapping the winner)
            j = next((int(o) for o in order[1:] if merged[int(o)].box.iou(merged[i].box) < 0.3), None)
            out[(s["sample_id"], ins["text"])] = (float(p[i]), merged[i], float(p[j]) if j is not None else 0.0)
    return out


def learned(cache: dict, tau: float, margin: float = 0.0):
    def choose(s, ins, merged):
        p, c, p2 = cache.get((s["sample_id"], ins["text"]), (0.0, None, 0.0))
        return c if (p >= tau and p - p2 >= margin) else None
    return choose


def all_scores(model, samples) -> list[tuple]:
    """Per instruction: (probabilities, candidates, target box) for conformal analysis."""
    out = []
    for s in samples:
        merged = candidates(s)
        if not merged:
            continue
        all_ins = [v for base in s["instructions"] for v in variants(s, base)]
        probs = model.predict_proba(np.array([r for ins in all_ins
                                              for r in feat(s, ins["text"], merged)]))[:, 1]
        for k, ins in enumerate(all_ins):
            tb = s["boxes"].get(ins["target_id"]) if ins["target_id"] else None
            out.append((probs[k * len(merged):(k + 1) * len(merged)], merged, tb))
    return out


def conformal(cal: list[tuple], test: list[tuple], alpha: float) -> dict:
    """Split conformal prediction sets over candidate locations.

    Calibration uses instructions that HAVE a target: nonconformity = 1 - p(true element).
    Set = candidates with p >= 1 - qhat, merged by location. ORION acts only when the set has exactly
    one location. The coverage guarantee holds only for data like the calibration set (same layout
    families); on held-out families it is measured, not promised.
    """
    scores = []
    for p, cands, tb in cal:
        if tb is not None:
            true = [p[i] for i, c in enumerate(cands) if hit(c, tb)]
            scores.append(1 - max(true) if true else 1.0)
    n = len(scores)
    if n < 20 or not test:
        return {"alpha": alpha, "skipped": f"too little data (calibration n={n}, test n={len(test)})"}
    qhat = float(np.quantile(scores, min(1.0, np.ceil((n + 1) * (1 - alpha)) / n), method="higher"))
    covered = total = 0
    sizes, counts = [], {"correct": 0, "wrong_click": 0, "missed": 0}
    for p, cands, tb in test:
        members = [cands[i] for i in np.where(p >= 1 - qhat)[0]]
        locations = []
        for c in sorted(members, key=lambda c: -c.box.area):
            if all(c.box.iou(l.box) < 0.3 and not l.box.contains(*c.box.center) for l in locations):
                locations.append(c)
        sizes.append(len(locations))
        if tb is not None:
            total += 1
            covered += any(hit(c, tb) for c in members)
        counts[outcome(locations[0] if len(locations) == 1 else None, tb)] += 1
    m = sum(counts.values())
    return {"alpha": alpha, "qhat": round(qhat, 4), "target_coverage": 1 - alpha,
            "empirical_coverage": round(covered / max(total, 1), 4), "mean_set_size": round(float(np.mean(sizes)), 3),
            "act_if_single": {"accuracy": round(counts["correct"] / m, 4),
                              "wrong_click_rate": round(counts["wrong_click"] / m, 4),
                              "missed_rate": round(counts["missed"] / m, 4)}}


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
    ap.add_argument("--visual", action="store_true", help="add frozen SigLIP similarity features")
    a = ap.parse_args()
    global VIS
    if a.visual:
        VIS = joblib.load(Path(a.data) / "siglip_sims.joblib")
    raw = Path(a.data, "samples.jsonl").read_bytes()
    samples = [json.loads(l) for l in raw.decode("utf-8").splitlines()]
    test = [s for s in samples if s["family"] in TEST_FAMILIES]
    rest = [s for s in samples if s["family"] not in TEST_FAMILIES]
    val = [s for s in rest if s["seed"] % 5 == 0]
    train = [s for s in rest if s["seed"] % 5 != 0]

    X, y = [], []
    for s, ins, tb, merged in examples(train):
        for c, row in zip(merged, feat(s, ins["text"], merged)):
            X.append(row)
            y.append(int(hit(c, tb)))
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0)
    model.fit(np.array(X), np.array(y))

    # Operating point from validation only. Product rule: never more wrong clicks than the current
    # rules (B4) on validation; within that budget, as many correct answers as possible.
    val_cache, test_cache = best_scores(model, val), best_scores(model, test)
    budget = evaluate("b4", val, rule(True, True))["wrong_click_rate"]
    best_tau, best_margin, best_acc = 0.95, 0.6, -1.0
    for tau in [i / 100 for i in range(20, 100, 2)]:
        for margin in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            r = evaluate("p0", val, learned(val_cache, tau, margin))
            if r["wrong_click_rate"] <= budget and r["accuracy"] > best_acc:
                best_tau, best_margin, best_acc = tau, margin, r["accuracy"]

    rules = [("B1 metadata only (rules)", rule(True, False)), ("B2 OCR only (rules)", rule(False, True)),
             ("B4 metadata + OCR (rules, current)", rule(True, True))]
    results = {"val": [evaluate(n, val, f) for n, f in rules] + [evaluate("P0 learned scorer", val,
                                                                         learned(val_cache, best_tau, best_margin))],
               "test": [evaluate(n, test, f) for n, f in rules] + [evaluate("P0 learned scorer", test,
                                                                           learned(test_cache, best_tau, best_margin))]}
    lo, hi = bootstrap_diff(results["test"][3]["_per"], results["test"][2]["_per"])
    test_all = all_scores(model, test)
    # Split validation BY PAGE (not by instruction): the 3 phrasings of an instruction are adjacent, so an
    # instruction-level alternation would give calibration and check different phrasing mixes.
    cal = all_scores(model, [s for i, s in enumerate(val) if i % 2 == 0])
    in_dist = all_scores(model, [s for i, s in enumerate(val) if i % 2 == 1])
    conformal_results = {f"alpha_{a}": {"same_families": conformal(cal, in_dist, a),
                                         "heldout_families": conformal(cal, test_all, a)} for a in (0.1, 0.05)}
    for split in results.values():
        for r in split:
            r.pop("_per")

    Path(a.model_out).parent.mkdir(parents=True, exist_ok=True)
    data_hash = hashlib.sha256(raw).hexdigest()[:16]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    joblib.dump({"model": model, "tau": best_tau, "margin": best_margin, "features": FEATURES + (["visual_sim", "visual_gap"] if VIS is not None else []), "visual": VIS is not None, "data_sha256": data_hash,
                 "commit": commit}, a.model_out)
    report = {"data": a.data, "data_sha256_16": data_hash, "git_commit": commit,
              "pages": {"train": len(train), "val": len(val), "test_heldout_families": len(test)},
              "test_families": sorted(TEST_FAMILIES), "train_rows": len(y), "positives": int(sum(y)),
              "abstain_threshold": best_tau, "ambiguity_margin": best_margin, "results": results,
              "test_accuracy_gain_P0_vs_B4_95ci": [lo, hi], "conformal": conformal_results}
    for k, v in conformal_results.items():
        for where, r in v.items():
            if "skipped" in r:
                print(f"CONFORMAL {k} {where}: {r['skipped']}")
                continue
            print(f"CONFORMAL {k} {where:<17} coverage {r['empirical_coverage']:.1%} (target {r['target_coverage']:.0%})"
                  f"  set size {r['mean_set_size']:.2f}  act-if-single: correct {r['act_if_single']['accuracy']:.1%}"
                  f" wrong {r['act_if_single']['wrong_click_rate']:.1%}")
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for r in results["test"]:
        print(f"TEST {r['method']:<36} correct {r['accuracy']:.1%}  wrong clicks {r['wrong_click_rate']:.1%}  "
              f"missed {r['missed_rate']:.1%}  (n={r['n']})  wrong by case: {r['wrong_clicks_by_case']}")
    print(f"P0 - B4 accuracy on held-out families: 95% CI [{lo:+.1%}, {hi:+.1%}]; abstain threshold {best_tau}, ambiguity margin {best_margin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
