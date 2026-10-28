"""Compute frozen SigLIP image-text similarity for every (instruction, candidate) in the rendered data.

For each page: crop every candidate (with a little context) from the screenshot, embed the crops and
the instruction targets, and store cosine similarities. train_grounding.py --visual uses them as one
extra feature. Output: DATA/siglip_sims.joblib (gitignored, in the data folder).

usage: python research/training/embed_siglip.py --data research/data_collection/out/v1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from train_grounding import candidates, variants  # noqa: E402

from orion.grounding.locate import parse_instruction  # noqa: E402

MODEL_ID = "google/siglip-base-patch16-224"
PAD = 8


def crop(img, box):
    """Crop with context, clamped to the image and never empty (some boxes lie partly off-screen)."""
    left = min(max(0, box.left - PAD), img.width - 1)
    top = min(max(0, box.top - PAD), img.height - 1)
    right = max(left + 1, min(img.width, box.right + PAD))
    bottom = max(top + 1, min(img.height, box.bottom + PAD))
    return img.crop((left, top, right, bottom))


def main() -> int:
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    data = Path(a.data)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained(MODEL_ID, torch_dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev)
    model.eval()
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    samples = [json.loads(l) for l in (data / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    sims: dict[str, np.ndarray] = {}
    t0 = time.monotonic()
    with torch.no_grad():
        for n, s in enumerate(samples, 1):
            cands = candidates(s)
            if not cands:
                continue
            img = Image.open(data / "png" / s["png"]).convert("RGB")
            crops = [crop(img, c.box) for c in cands]
            texts = sorted({parse_instruction(v["text"])[0] or "unknown"
                            for b in s["instructions"] for v in variants(s, b)})
            ii = proc(images=crops, return_tensors="pt").to(dev)
            ti = proc(text=texts, padding="max_length", return_tensors="pt").to(dev)
            ie = model.get_image_features(**ii)
            te = model.get_text_features(**ti)
            # transformers 5.x returns an output object; older versions return the tensor itself
            ie = ie if isinstance(ie, torch.Tensor) else ie.pooler_output
            te = te if isinstance(te, torch.Tensor) else te.pooler_output
            ie = torch.nn.functional.normalize(ie.float(), dim=-1)
            te = torch.nn.functional.normalize(te.float(), dim=-1)
            m = (te @ ie.T).cpu().numpy()          # texts x candidates
            for k, t in enumerate(texts):
                sims[f"{s['sample_id']}|{t}"] = m[k].astype(np.float16)
            if n % 100 == 0:
                print(f"{n}/{len(samples)} pages, {time.monotonic() - t0:.0f}s", flush=True)
    import joblib
    joblib.dump(sims, data / "siglip_sims.joblib")
    print(f"done: {len(sims)} instruction-target rows in {time.monotonic() - t0:.0f}s on {dev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
