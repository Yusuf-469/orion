"""Features for the learned grounding scorer (P0). Shared by training and the live product.

One row per (instruction, candidate). The model scores rows; ORION picks the best candidate
and abstains when the best probability is below a threshold chosen on validation data.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from orion.grounding.locate import Candidate, _norm, parse_instruction

FEATURES = [
    "text_sim", "exact", "token_overlap", "role_given", "role_match", "has_role",
    "src_meta", "src_ocr", "src_both", "ocr_conf", "n_same_text", "container_given",
    "heading_dist", "dup_rank_by_heading", "rel_x", "rel_y", "rel_w", "rel_h", "disabled", "sim_gap",
]


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[3] / "artifacts" / "models" / "grounding_p0.joblib"
_bundle_cache: dict = {}


def load_model(path: Path | str = MODEL_PATH):
    """The trained scorer bundle, or None if it has not been trained on this machine (then rules are used)."""
    p = Path(path)
    if not p.is_file():
        return None
    key = (str(p.resolve()), p.stat().st_mtime)
    if key not in _bundle_cache:
        import joblib
        _bundle_cache.clear()
        _bundle_cache[key] = joblib.load(p)
    return _bundle_cache[key]


def locate_learned(description: str, cands: list[Candidate], bundle: dict, window,
                   visual: list[float] | None = None) -> "Located":
    """Pick a candidate with the learned scorer; abstain below the trained threshold.

    `window` is the window's screen Box: boxes are made window-relative, as in training.
    """
    import numpy as np

    from orion.grounding.locate import Located
    from orion.grounding.screen import Box
    if not cands:
        return Located(None, 0.0, "nothing visible in the window")
    rel = [Candidate(c.text, Box(c.box.left - window.left, c.box.top - window.top, c.box.right - window.left,
                                 c.box.bottom - window.top), c.source, c.role, c.confidence, c.invokable, c.disabled)
           for c in cands]
    w, h = window.right - window.left, window.bottom - window.top
    rows = featurize(description, rel, w, h)
    if bundle.get("visual"):
        if visual is None:
            raise ValueError("this grounding model needs visual (SigLIP) features; none were provided")
        rows = add_visual(rows, visual)
    p = bundle["model"].predict_proba(np.array(rows))[:, 1]
    order = p.argsort()[::-1]
    i = int(order[0])
    if p[i] < bundle["tau"]:
        return Located(None, float(p[i]), f"not confident enough (best '{cands[i].text}' {p[i]:.2f} "
                                          f"< {bundle['tau']:.2f}); not clicking")
    j = next((int(o) for o in order[1:] if cands[int(o)].box.iou(cands[i].box) < 0.3), None)
    if j is not None and p[i] - p[j] < bundle.get("margin", 0.0):
        return Located(None, float(p[i]), f"ambiguous: '{cands[i].text}' ({p[i]:.2f}) and '{cands[j].text}' "
                                          f"({p[j]:.2f}) are both likely; not clicking", cands[j])
    return Located(cands[i], float(p[i]), f"found '{cands[i].text}' via {cands[i].source} "
                                          f"(learned score {p[i]:.2f})", cands[j] if j is not None else None)


VISUAL_FEATURES = ["visual_sim", "visual_gap"]


def add_visual(rows: list[list[float]], visual: list[float]) -> list[list[float]]:
    """Append image-text similarity (SigLIP) features: the candidate's own and its gap to the best."""
    best = max(visual, default=0.0)
    return [r + [float(v), float(best - v)] for r, v in zip(rows, visual)]


def featurize(description: str, cands: list[Candidate], width: int, height: int) -> list[list[float]]:
    target, role, container = parse_instruction(description)
    sims = [_sim(target, c.text) for c in cands]
    best = max(sims, default=0.0)
    # Headings for the container hint: candidates whose text matches "in the <container>".
    heads = [c for c in cands if container and _sim(container, c.text) > 0.85]
    dists = []
    for c in cands:
        above = [c.box.top - h.box.bottom for h in heads if h.box.bottom <= c.box.top + 2]
        dists.append(min(above) / max(height, 1) if above else 1.0)
    rows = []
    for i, c in enumerate(cands):
        same = [j for j, s in enumerate(sims) if s > 0.9 and j != i]
        rank = sum(1 for j in same if dists[j] < dists[i])
        tt, ct = set(target.split()), set(_norm(c.text).split())
        rows.append([
            sims[i], float(_norm(c.text) == target), len(tt & ct) / max(len(tt | ct), 1),
            float(role is not None), float(role is not None and c.role == role), float(bool(c.role)),
            float(c.source == "uia"), float(c.source == "ocr"), float(c.source == "uia+ocr"),
            c.confidence if c.source != "uia" else 1.0, float(len(same)), float(container is not None),
            dists[i], float(rank), c.box.left / max(width, 1), c.box.top / max(height, 1),
            (c.box.right - c.box.left) / max(width, 1), (c.box.bottom - c.box.top) / max(height, 1),
            float(c.disabled), best - sims[i],
        ])
    return rows
