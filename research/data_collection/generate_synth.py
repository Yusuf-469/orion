"""Write a synthetic UI batch: one HTML file per sample plus a JSONL manifest.

usage: python research/data_collection/generate_synth.py --out research/data_collection/out/v0 \
           --n 60 [--seed0 0] [--off theme,font]

Ground truth is in the manifest (element ids, roles, labels, flags). Bounding
boxes are added in Stage 4 by rendering with Playwright.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from orion.grounding.synth import Factors, generate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--off", default="", help="comma-separated factors to switch off")
    a = ap.parse_args()
    off = [x for x in a.off.split(",") if x]
    factors = Factors(**{k: False for k in off})
    out = Path(a.out)
    (out / "html").mkdir(parents=True, exist_ok=True)
    flags, n_instr, n_abstain = Counter(), 0, 0
    with open(out / "manifest.jsonl", "w", encoding="utf-8") as mf:
        for seed in range(a.seed0, a.seed0 + a.n):
            s = generate(seed, factors=factors)
            (out / "html" / f"{s.sample_id}.html").write_text(s.html, encoding="utf-8")
            row = s.model_dump(exclude={"html"})
            row["html_sha256"] = hashlib.sha256(s.html.encode()).hexdigest()
            mf.write(json.dumps(row, ensure_ascii=False) + "\n")
            for i in s.instructions:
                n_instr += 1
                n_abstain += i.target_id is None
                flags.update(i.flags)
    summary = {"samples": a.n, "instructions": n_instr, "abstain_targets": n_abstain, "factors_off": off,
               "flag_counts": dict(flags)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
