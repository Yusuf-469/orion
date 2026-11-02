"""What the screen shows that UI Automation does not: detector boxes + OCR text, as plain elements.

Used by desktop.look so the agent can see controls an app draws itself (canvas apps, games, some
Electron/Java apps). Pure functions; the capture, OCR and detector live in screen.py / detector.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from orion.grounding.screen import Box, OcrWord


@dataclass(frozen=True)
class Seen:
    name: str            # text read inside it; "" for an unlabeled icon
    role: str            # "control" (detected, with text), "icon" (detected, no text), "text" (OCR only)
    box: Box             # screen coordinates
    confidence: float


def _inside(b: Box, outer: Box) -> bool:
    return outer.contains(*b.center)


def elements(words: list[OcrWord], detected: list[tuple[Box, float]], known: list[Box]) -> list[Seen]:
    """Merge detector boxes and OCR words, dropping anything already covered by a known (UIA) element."""
    def covered(b: Box) -> bool:
        return any(_inside(b, k) or b.iou(k) > 0.3 for k in known)

    used: set[int] = set()
    out: list[Seen] = []
    for box, conf in sorted(detected, key=lambda d: (d[0].top, d[0].left)):
        inner = [(i, w) for i, w in enumerate(words) if i not in used and _inside(w.box, box)]
        used.update(i for i, _ in inner)
        label = " ".join(w.text for _, w in sorted(inner, key=lambda iw: (iw[1].box.top // 8, iw[1].box.left)))
        if not covered(box):
            out.append(Seen(label[:120], "control" if label else "icon", box, round(conf, 3)))
    for i, w in enumerate(words):
        if i not in used and w.text and not covered(w.box):
            out.append(Seen(w.text[:120], "text", w.box, round(w.confidence, 3)))
    return sorted(out, key=lambda s: (s.box.top // 10, s.box.left))


def where(box: Box, win: Box) -> str:
    """Plain-words position of a box inside the window, e.g. 'top left'."""
    x, y = box.center
    w, h = max(win.right - win.left, 1), max(win.bottom - win.top, 1)
    col = ("left", "middle", "right")[min(2, max(0, 3 * (x - win.left) // w))]
    row = ("top", "middle", "bottom")[min(2, max(0, 3 * (y - win.top) // h))]
    return "centre" if (row, col) == ("middle", "middle") else f"{row} {col}"
