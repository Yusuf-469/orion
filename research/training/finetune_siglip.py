"""P1: fine-tune SigLIP (LoRA) to rank the right on-screen element for an instruction.

Training pages only (training families, seed % 5 != 0); validation and held-out families are never seen.
Per page: crops of all candidates + the targets of its instructions; listwise loss = cross-entropy over
the page's candidates, with all candidates that hit the target counted as correct (multi-positive).
Saves a LoRA adapter (small) to artifacts/models/siglip_lora (gitignored).

usage: python research/training/finetune_siglip.py --data research/data_collection/out/v1 --epochs 2
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from embed_siglip import MODEL_ID, crop  # noqa: E402
from train_grounding import TEST_FAMILIES, candidates, hit, variants  # noqa: E402

from orion.grounding.locate import parse_instruction  # noqa: E402


def pooled(x, torch):
    return x if isinstance(x, torch.Tensor) else x.pooler_output


def main() -> int:
    import torch
    from peft import LoraConfig, get_peft_model
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--out", default="artifacts/models/siglip_lora")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    random.seed(a.seed)
    torch.manual_seed(a.seed)
    data = Path(a.data)
    dev = "cuda"
    samples = [json.loads(l) for l in (data / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    train = [s for s in samples if s["family"] not in TEST_FAMILIES and s["seed"] % 5 != 0]

    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(dev)
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                                             target_modules=["q_proj", "v_proj"]))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"LoRA trainable params: {trainable:,}; train pages: {len(train)}", flush=True)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    scaler = torch.amp.GradScaler("cuda")

    # Pre-build page tensors once (crops + target texts + positive masks).
    pages = []
    for s in train:
        cands = candidates(s)
        if len(cands) < 2:
            continue
        img = Image.open(data / "png" / s["png"]).convert("RGB")
        items = {}
        for base in s["instructions"]:
            for v in variants(s, base):
                tb = s["boxes"].get(v["target_id"]) if v["target_id"] else None
                if tb is None:
                    continue
                t = parse_instruction(v["text"])[0] or "unknown"
                items.setdefault(t, [hit(c, tb) for c in cands])
        if items:
            pages.append(([crop(img, c.box) for c in cands], list(items), list(items.values())))

    t0 = time.monotonic()
    model.train()
    for ep in range(a.epochs):
        random.shuffle(pages)
        total, n = 0.0, 0
        for crops, texts, masks in pages:
            ii = proc(images=crops, return_tensors="pt").to(dev)
            ti = proc(text=texts, padding="max_length", return_tensors="pt").to(dev)
            pos = torch.tensor(masks, dtype=torch.bool, device=dev)          # texts x candidates
            with torch.autocast("cuda", dtype=torch.float16):
                ie = torch.nn.functional.normalize(pooled(model.get_image_features(**ii), torch).float(), dim=-1)
                te = torch.nn.functional.normalize(pooled(model.get_text_features(**ti), torch).float(), dim=-1)
                logits = (te @ ie.T) * 20.0                                    # fixed temperature
            logp = torch.log_softmax(logits.float(), dim=-1)
            keep = pos.any(dim=1)
            loss = -(torch.logsumexp(logp.masked_fill(~pos, -1e4), dim=-1))[keep].mean()
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            total += float(loss)
            n += 1
        print(f"epoch {ep + 1}: mean loss {total / max(n, 1):.4f} ({time.monotonic() - t0:.0f}s)", flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out)
    print(f"saved LoRA adapter to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
