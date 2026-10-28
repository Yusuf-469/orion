"""Render synthetic UI pages and record what ORION would see on each.

For every sample: a screenshot (PNG), the on-screen box of every element (from the DOM), the
page's own metadata candidates (role + accessible name + box, like UI Automation would give),
and local OCR of the screenshot. Output goes to OUT (gitignored); nothing personal is involved.

usage: python research/data_collection/render_synth.py --out research/data_collection/out/v1 --n 300
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from orion.grounding.synth import FAMILIES, generate

_ROLE = {"button": "ButtonControl", "link": "HyperlinkControl", "checkbox": "CheckBoxControl",
         "textbox": "EditControl", "tab": "TabItemControl", "menuitem": "MenuItemControl"}


def render(n: int, seed0: int, out: Path) -> None:
    from playwright.sync_api import sync_playwright
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    from PIL import Image

    (out / "png").mkdir(parents=True, exist_ok=True)
    ocr = RapidOCR()
    t_render = t_ocr = 0.0
    with sync_playwright() as pw, open(out / "samples.jsonl", "w", encoding="utf-8") as mf:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        for seed in range(seed0, seed0 + n):
            s = generate(seed, family=FAMILIES[seed % len(FAMILIES)])
            t0 = time.monotonic()
            page.set_content(s.html, wait_until="load")
            boxes, meta = {}, []
            for e in s.elements:
                loc = page.locator(f'[data-orion-id="{e.id}"]')
                b = loc.bounding_box() if not e.hidden else None
                if b and b["width"] > 0 and b["height"] > 0:
                    box = [round(b["x"]), round(b["y"]), round(b["x"] + b["width"]), round(b["y"] + b["height"])]
                    boxes[e.id] = box
                    meta.append({"text": e.label, "box": box, "role": _ROLE[e.role], "disabled": e.disabled})
            headings = []
            for h in page.locator("section").all():
                hb, sb = h.locator("h2").bounding_box(), h.bounding_box()
                if hb and sb:
                    headings.append({"text": h.get_attribute("aria-label"),
                                     "box": [round(hb["x"]), round(hb["y"]), round(hb["x"] + hb["width"]),
                                             round(hb["y"] + hb["height"])],
                                     "section": [round(sb["x"]), round(sb["y"]), round(sb["x"] + sb["width"]),
                                                 round(sb["y"] + sb["height"])]})
            png = out / "png" / f"{s.sample_id}.png"
            page.screenshot(path=str(png), full_page=False)
            t_render += time.monotonic() - t0
            t0 = time.monotonic()
            result, _ = ocr(np.asarray(Image.open(png).convert("RGB"))[:, :, ::-1])
            t_ocr += time.monotonic() - t0
            words = [{"text": t.strip(), "conf": float(c),
                      "box": [int(min(p[0] for p in pts)), int(min(p[1] for p in pts)),
                              int(max(p[0] for p in pts)), int(max(p[1] for p in pts))]}
                     for pts, t, c in (result or [])]
            row = s.model_dump(exclude={"html"})
            row.update(boxes=boxes, metadata=meta, headings=headings, ocr=words, png=png.name)
            mf.write(json.dumps(row, ensure_ascii=False) + "\n")
            if (seed - seed0 + 1) % 25 == 0:
                print(f"{seed - seed0 + 1}/{n} pages  render {t_render:.0f}s  ocr {t_ocr:.0f}s", flush=True)
        browser.close()
    print(f"done: {n} pages, render {t_render:.1f}s, ocr {t_ocr:.1f}s ({t_ocr / n:.2f}s/page)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed0", type=int, default=0)
    a = ap.parse_args()
    render(a.n, a.seed0, Path(a.out))
