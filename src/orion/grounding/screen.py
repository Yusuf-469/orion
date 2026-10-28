"""Window capture and OCR for visual grounding.

Captures ONLY the target window's rectangle (never the whole screen), in physical pixels so
coordinates stay correct on mixed-DPI setups (this machine: 100% and 125% monitors).
Screenshots stay in memory; nothing is written to disk.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from functools import lru_cache

_DPI_SET = False


def ensure_dpi_aware() -> None:
    """Per-monitor DPI awareness (v2) so window rects, screenshots and clicks share one pixel space."""
    global _DPI_SET
    if sys.platform == "win32" and not _DPI_SET:
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        _DPI_SET = True


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)

    def iou(self, o: "Box") -> float:
        inter = Box(max(self.left, o.left), max(self.top, o.top), min(self.right, o.right), min(self.bottom, o.bottom))
        a = inter.area
        return a / (self.area + o.area - a) if a else 0.0

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


def window_rect(hwnd: int) -> Box:
    from ctypes import wintypes
    ensure_dpi_aware()
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return Box(r.left, r.top, r.right, r.bottom)


def capture_window(hwnd: int):
    """Screenshot of just this window's rectangle (PIL image, kept in memory) and its screen box."""
    from PIL import ImageGrab
    box = window_rect(hwnd)
    img = ImageGrab.grab(bbox=(box.left, box.top, box.right, box.bottom), all_screens=True)
    return img, box


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


@dataclass(frozen=True)
class OcrWord:
    text: str
    box: Box          # screen coordinates
    confidence: float


def ocr_window(hwnd: int) -> list[OcrWord]:
    """Local OCR (RapidOCR, CPU) of one window. Returns text boxes in screen coordinates."""
    import numpy as np
    img, win = capture_window(hwnd)
    result, _ = _ocr_engine()(np.asarray(img.convert("RGB"))[:, :, ::-1])
    words = []
    for pts, text, conf in result or []:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        words.append(OcrWord(text.strip(), Box(int(min(xs)) + win.left, int(min(ys)) + win.top,
                                               int(max(xs)) + win.left, int(max(ys)) + win.top), float(conf)))
    return words
