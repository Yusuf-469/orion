"""Interactive-element detector: finds buttons, icons and fields in a window screenshot, with or without text.

Adapted from Microsoft OmniParser's YOLOv9 detector wrapper (util/yolov9.py, MIT; weight
`icon_detect_v3`, MIT, see docs/THIRD_PARTY.md). It is the third candidate source for grounding,
beside UI Automation and OCR: it sees controls an app draws itself. The weight is local
(models/omniparser/icon_detect_v3/model.pt); without it, or without PyTorch, detect() returns [] and
ORION works as before. Screenshots stay in memory.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from orion import resources
from orion.grounding.screen import Box

log = logging.getLogger("orion.grounding")
WEIGHT = resources.path("models", "omniparser", "icon_detect_v3", "model.pt")
STRIDES = (8, 16, 32)


@lru_cache(maxsize=1)
def _model():
    """(torch module, device) or None when the weight or PyTorch is missing."""
    if not WEIGHT.is_file():
        log.info("detector weight not found at %s; vision uses OCR only", WEIGHT)
        return None
    try:
        import torch
        # The profiling executor re-optimises the graph on the first calls: 134 s first call measured
        # here, against 15 s without it. Predictable start-up matters more than the last few ms.
        torch._C._jit_set_profiling_executor(False)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.jit.load(str(WEIGHT), map_location=device).eval(), device
    except Exception as e:  # noqa: BLE001 - a broken install must not break the desktop tools
        log.warning("detector not usable (%s); vision uses OCR only", e)
        return None


def available() -> bool:
    return _model() is not None


def warm_up_in_background() -> None:
    """Load the model and run one blank image off the UI thread, so the first real look is fast."""
    import threading

    def go():
        try:
            from PIL import Image
            detect(Image.new("RGB", (640, 400), (30, 30, 40)))
        except Exception as e:  # noqa: BLE001
            log.warning("detector warm-up failed: %s", e)
    threading.Thread(target=go, name="detector-warmup", daemon=True).start()


def _run(model, device, img, conf: float, imgsz: int, iou: float):
    import numpy as np
    import torch
    from PIL import Image
    from torchvision.ops import batched_nms

    w0, h0 = img.size
    side = ((imgsz + 31) // 32) * 32
    scale = min(side / w0, side / h0)
    rw, rh = int(w0 * scale), int(h0 * scale)
    pl, pt = (side - rw) // 2, (side - rh) // 2
    canvas = Image.new("RGB", (side, side), (114, 114, 114))
    canvas.paste(img.convert("RGB").resize((rw, rh), Image.Resampling.LANCZOS), (pl, pt))
    x = torch.from_numpy(np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1) / 255.0).unsqueeze(0).to(device)
    amp = torch.autocast("cuda", dtype=torch.float16) if device.type == "cuda" else torch.autocast("cpu", enabled=False)
    with torch.inference_mode(), amp, torch.jit.optimized_execution(False):
        outs = model(x)
        logits, boxes = [], []
        for k, stride in zip(range(0, len(outs), 2), STRIDES):   # anchor-free decode, as in OmniParser
            lg, dist = outs[k], outs[k + 1]
            b, _, hh, ww = lg.shape
            logits.append(lg.permute(0, 2, 3, 1).reshape(b, -1, lg.shape[1]))
            dist = dist.permute(0, 2, 3, 1).reshape(b, -1, 4) * stride
            gy, gx = torch.meshgrid(torch.arange(hh, device=device), torch.arange(ww, device=device), indexing="ij")
            anchor = (torch.stack((gx, gy), -1).reshape(-1, 2) + 0.5) * stride
            lt, rb = dist.chunk(2, -1)
            boxes.append(torch.cat((anchor - lt, anchor + rb), -1))
        scores, cls = torch.cat(logits, 1).sigmoid()[0].max(-1)
        bx = torch.cat(boxes, 1)[0].float()
        keep = scores > conf
        scores, cls, bx = scores[keep].float(), cls[keep], bx[keep]
        bx[:, [0, 2]] = ((bx[:, [0, 2]] - pl) / scale).clamp(0, w0)
        bx[:, [1, 3]] = ((bx[:, [1, 3]] - pt) / scale).clamp(0, h0)
        idx = batched_nms(bx, scores, cls, iou)[:300]
        return [(bx[i].tolist(), float(scores[i])) for i in idx]


def detect(img, offset: tuple[int, int] = (0, 0), conf: float = 0.25, imgsz: int = 1280,
           iou: float = 0.5) -> list[tuple[Box, float]]:
    """Boxes of interactive elements in a PIL image, shifted by `offset` (the window's screen origin)."""
    m = _model()
    if m is None:
        return []
    model, device = m
    try:
        found = _run(model, device, img, conf, imgsz, iou)
    except RuntimeError as e:   # e.g. GPU memory taken by the local LLM: retry on the CPU once
        if device.type != "cuda":
            raise
        import torch
        log.warning("detector on GPU failed (%s); using the CPU", e)
        _model.cache_clear()
        cpu = torch.jit.load(str(WEIGHT), map_location="cpu").eval()
        found = _run(cpu, torch.device("cpu"), img, conf, imgsz, iou)
    ox, oy = offset
    return [(Box(int(x1) + ox, int(y1) + oy, int(x2) + ox, int(y2) + oy), s) for (x1, y1, x2, y2), s in found
            if x2 - x1 >= 4 and y2 - y1 >= 4]
