import numpy as np

from orion.grounding.features import FEATURES, featurize, locate_learned
from orion.grounding.locate import Candidate
from orion.grounding.screen import Box


class SimModel:
    """Stand-in model: probability = text similarity feature (column 0)."""
    def __init__(self):
        self.seen = None

    def predict_proba(self, X):
        self.seen = X
        p = np.clip(X[:, 0], 0, 1)
        return np.stack([1 - p, p], axis=1)


def cands(offset=0):
    return [Candidate("Open", Box(10 + offset, 10 + offset, 70 + offset, 30 + offset), "ocr", "", 0.99),
            Candidate("Export", Box(100 + offset, 10 + offset, 170 + offset, 30 + offset), "ocr", "", 0.99)]


def test_feature_rows_match_feature_names():
    rows = featurize("the Export button in the toolbar", cands(), 800, 600)
    assert len(rows) == 2 and all(len(r) == len(FEATURES) for r in rows)


def test_picks_best_and_uses_window_relative_coordinates():
    m = SimModel()
    win = Box(-1700, 250, -900, 850)   # a window on a left-hand monitor; candidates in screen coordinates
    on_screen = [Candidate(c.text, Box(c.box.left - 1700, c.box.top + 250, c.box.right - 1700, c.box.bottom + 250),
                           c.source, c.role, c.confidence) for c in cands()]
    r = locate_learned("Export", on_screen, {"model": m, "tau": 0.5}, win)
    assert r.candidate.text == "Export"
    rel_x = m.seen[:, FEATURES.index("rel_x")]
    assert (rel_x >= 0).all() and (rel_x <= 1).all()   # boxes were made relative to the window


def test_abstains_below_threshold():
    r = locate_learned("Delete", cands(), {"model": SimModel(), "tau": 0.9}, Box(0, 0, 800, 600))
    assert r.candidate is None and "not confident enough" in r.reason
