"""Find a UI element from a short description, using UI Automation AND what is visible (OCR).

This is the rule-based hybrid (baseline B4 in the research plan); a learned scorer can replace
`score()` later without changing callers. It abstains instead of guessing:
  - nothing scores above THRESHOLD                         -> not found
  - two different places score within MARGIN of each other -> ambiguous
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from orion.grounding.screen import Box, OcrWord

THRESHOLD = 0.75
MARGIN = 0.06
_ROLE_WORDS = {"button": "ButtonControl", "link": "HyperlinkControl", "tab": "TabItemControl",
               "checkbox": "CheckBoxControl", "menu": "MenuItemControl", "field": "EditControl"}


@dataclass(frozen=True)
class Candidate:
    text: str
    box: Box
    source: Literal["uia", "ocr", "uia+ocr"]
    role: str = ""          # UIA control type, if known
    confidence: float = 1.0
    invokable: bool = False


@dataclass(frozen=True)
class Located:
    candidate: Candidate | None
    score: float
    reason: str
    runner_up: Candidate | None = None


def parse_target(description: str) -> tuple[str, str | None]:
    """'the Export button' -> ('export', 'ButtonControl'); quoted text wins."""
    q = re.search(r"[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]", description)
    words = description.strip().lower()
    role = next((r for w, r in _ROLE_WORDS.items() if re.search(rf"\b{w}\b", words)), None)
    if q:
        return _norm(q.group(1)), role
    words = re.sub(r"^(the|a|an)\s+", "", words)
    words = re.sub(r"\s+(button|link|tab|checkbox|menu|field)$", "", words)
    return _norm(words), role


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def text_similarity(target: str, text: str) -> float:
    t = _norm(text)
    if not t or not target:
        return 0.0
    if t == target:
        return 1.0
    return SequenceMatcher(None, target, t).ratio()


def merge(uia: list[Candidate], ocr: list[OcrWord]) -> list[Candidate]:
    """UIA elements plus OCR text; where both see the same thing, keep one 'uia+ocr' candidate."""
    out = list(uia)
    for w in ocr:
        match = next((i for i, c in enumerate(out) if c.source == "uia" and c.box.iou(w.box) > 0.1
                      and c.box.contains(*w.box.center) and text_similarity(_norm(c.text), w.text) > 0.8), None)
        if match is not None:
            c = out[match]
            out[match] = Candidate(c.text, c.box, "uia+ocr", c.role, max(c.confidence, w.confidence), c.invokable)
        else:
            out.append(Candidate(w.text, w.box, "ocr", "", w.confidence, False))
    return out


def score(c: Candidate, target: str, role: str | None) -> float:
    s = text_similarity(target, c.text)
    if c.source == "ocr":
        s *= 0.85 + 0.15 * c.confidence
    if role and c.role == role:
        s += 0.05
    if c.source == "uia+ocr":
        s += 0.05      # two independent sources agree
    return min(s, 1.0)


def locate(description: str, candidates: list[Candidate]) -> Located:
    target, role = parse_target(description)
    if not target:
        return Located(None, 0.0, "empty description")
    ranked = sorted(((score(c, target, role), c) for c in candidates), key=lambda t: -t[0])
    if not ranked or ranked[0][0] < THRESHOLD:
        best = ranked[0] if ranked else (0.0, None)
        return Located(None, best[0], f"no visible element matches '{target}' well enough"
                       + (f" (closest: '{best[1].text}', {best[0]:.2f})" if best[1] else ""))
    s1, c1 = ranked[0]
    rival = next(((s, c) for s, c in ranked[1:] if c.box.iou(c1.box) < 0.3), None)
    if rival and rival[0] >= THRESHOLD and s1 - rival[0] < MARGIN:
        return Located(None, s1, f"ambiguous: '{c1.text}' and '{rival[1].text}' both match '{target}'",
                       runner_up=rival[1])
    return Located(c1, s1, f"found '{c1.text}' via {c1.source} (score {s1:.2f})", rival[1] if rival else None)
