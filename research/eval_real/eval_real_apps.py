"""Real-app grounding check: how well does ORION find controls in real Windows apps it was never trained on?

PROTOCOL (fixed before the first run; nothing is tuned on these results)
- Apps: ORION's OWN new windows of Calculator (Standard mode) and Paint (blank canvas). Nothing else on
  screen is used; no personal content. Each app is measured at its opening size and at a second size
  (ORION resizes its own window), because layout changes with size. Nothing is clicked.
- Answer key: UI Automation. Every enabled, on-screen, named control of a clickable type (button, menu
  item, tab, list item, check box, radio button, link, split button) inside the window, excluding the
  window frame's Minimize/Maximize/Close. If two such controls in different places share a name, the
  right answer is to abstain.
- Instruction: the control's name (e.g. "Paste"), as a user would say it.
- Correct = the point ORION would click lies inside the target control's box. Wrong = a click anywhere
  else (including on a duplicate when it should have abstained). Gave up = abstained.
- Conditions:
    hybrid   = UIA metadata + OCR (what screen.click uses), learned scorer and rules (B4)
    ocr only = metadata hidden (as in apps whose controls UIA cannot see), learned and rules (B2)
    uia only = metadata without OCR, rules (B1)
  OCR-only is also reported on the subset whose name is actually visible as text in the control
  (icon and symbol buttons, e.g. Calculator's "Seven" shown as "7", cannot be found by reading).
- Screenshots stay in memory. Output: research/reports/grounding_real_v1.json (no images, no text other
  than control names).

usage: python research/eval_real/eval_real_apps.py
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from orion.grounding.features import load_model, locate_learned
from orion.grounding.locate import Candidate, _norm, collapse_nested, locate, merge, text_similarity
from orion.grounding.screen import Box, ensure_dpi_aware, ocr_window, window_rect
from orion.tools.windows.notepad import _uia
from orion.tools.windows.screen_click import _FRAME_IDS, _root_window_at

SYS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
APPS = {
    "calculator": ([os.path.join(SYS, "calc.exe")], lambda n: n == "Calculator"),
    "paint": ([shutil.which("mspaint") or os.path.join(SYS, "mspaint.exe")], lambda n: n.endswith("- Paint")),
    # added in v2, never inspected before measuring: a fresh check for the nested-element fix
    "charmap": ([os.path.join(SYS, "charmap.exe")], lambda n: n == "Character Map"),
}
# Controls that can show the signed-in user's identity are skipped (the v1 report captured one; scrubbed).
PERSONAL = re.compile(r"signed in|account|profile|@|" + re.escape(os.environ.get("USERNAME", "\0")), re.I)
CLICKABLE = {"ButtonControl", "MenuItemControl", "TabItemControl", "ListItemControl", "CheckBoxControl",
             "RadioButtonControl", "HyperlinkControl", "SplitButtonControl"}
SIZES = {"calculator": [None, (420, 720)], "paint": [None, (1000, 700)], "charmap": [None]}
OUT = Path(__file__).resolve().parents[1] / "reports" / "grounding_real_v2.json"   # v1: before collapse_nested


def open_own_window(auto, app):
    cmd, match = APPS[app]
    before = {w.NativeWindowHandle for w in auto.GetRootControl().GetChildren()}
    subprocess.Popen(cmd, close_fds=True)
    end = time.monotonic() + 20
    while time.monotonic() < end:
        w = next((w for w in auto.GetRootControl().GetChildren()
                  if w.NativeWindowHandle not in before and match(w.Name)), None)
        if w is not None:
            time.sleep(2.0)   # let the UI finish laying out
            return w
        time.sleep(0.2)
    raise RuntimeError(f"no new {app} window appeared")


def controls(auto, win, rect: Box):
    """(answer-key controls, metadata candidates) in screen coordinates."""
    keys, cands = [], []
    for c, _ in auto.WalkControl(win, maxDepth=14):
        if not c.Name or c.ControlTypeName in ("WindowControl", "TitleBarControl", "PaneControl"):
            continue
        if PERSONAL.search(c.Name):   # e.g. Paint's "Signed in as <name>": never stored in a report
            continue
        if c.AutomationId in _FRAME_IDS or c.GetParentControl().ControlTypeName == "TitleBarControl":
            continue
        r = c.BoundingRectangle
        b = Box(r.left, r.top, r.right, r.bottom)
        if b.area <= 0 or c.IsOffscreen or not rect.contains(*b.center):
            continue
        cand = Candidate(c.Name, b, "uia", c.ControlTypeName, 1.0, False, not c.IsEnabled)
        cands.append(cand)
        if c.ControlTypeName in CLICKABLE and c.IsEnabled:
            keys.append(cand)
    return keys, cands


def resize(hwnd: int, size) -> None:
    if size is None:
        return
    r = window_rect(hwnd)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, r.left, r.top, size[0], size[1], 0x0014)  # NOZORDER|NOACTIVATE
    time.sleep(1.5)


def fully_visible(hwnd: int, rect: Box) -> bool:
    """Every point of a 9x9 grid inside the window belongs to the window (nothing else is on top)."""
    w, h = rect.right - rect.left, rect.bottom - rect.top
    return all(_root_window_at(rect.left + w * (2 * i + 1) // 18, rect.top + h * (2 * j + 1) // 18) == hwnd
               for i in range(9) for j in range(9))


def judge(found, key: Candidate, should_abstain: bool) -> str:
    if found.candidate is None:
        return "abstain"
    if should_abstain:
        return "wrong"
    return "correct" if key.box.contains(*found.candidate.box.center) else "wrong"


def main() -> int:
    ensure_dpi_aware()
    bundle = load_model()
    if bundle is None:
        print("no learned model at artifacts/models/grounding_p0.joblib; train it first")
        return 1
    rows = []
    with _uia() as auto:
        for app in APPS:
            win = open_own_window(auto, app)
            hwnd = win.NativeWindowHandle
            try:
                for size in SIZES[app]:
                    resize(hwnd, size)
                    win.SetTopmost(True)   # ORION's own window stays on top while it is read
                    win.SetActive()
                    time.sleep(0.8)
                    rect = window_rect(hwnd)
                    if not fully_visible(hwnd, rect):
                        raise RuntimeError(f"{app} window is covered; refusing to read the screen")
                    keys, meta = controls(auto, win, rect)
                    ocr = [w for w in ocr_window(hwnd) if rect.contains(*w.box.center)]
                    hybrid = merge(meta, ocr)
                    ocr_only = merge([], ocr)
                    hybrid2 = collapse_nested(hybrid)
                    names = Counter(_norm(k.text) for k in keys)
                    for k in keys:
                        n = _norm(k.text)
                        dup = names[n] > 1 and any(o is not k and _norm(o.text) == n and o.box.iou(k.box) < 0.3
                                                   for o in keys)
                        visible = any(k.box.contains(*w.box.center) and text_similarity(n, w.text) > 0.8
                                      for w in ocr)
                        r = {"app": app, "size": "default" if size is None else f"{size[0]}x{size[1]}",
                             "name": k.text, "role": k.role, "should_abstain": dup, "visible_text": visible}
                        r["hybrid_learned"] = judge(locate_learned(k.text, hybrid, bundle, rect), k, dup)
                        r["hybrid_rules"] = judge(locate(k.text, hybrid), k, dup)
                        r["ocr_learned"] = judge(locate_learned(k.text, ocr_only, bundle, rect), k, dup)
                        r["ocr_rules"] = judge(locate(k.text, ocr_only), k, dup)
                        r["uia_rules"] = judge(locate(k.text, meta), k, dup)
                        # v2: nested same-name elements folded into one candidate (what screen.click does now)
                        r["hybrid_learned_v2"] = judge(locate_learned(k.text, hybrid2, bundle, rect), k, dup)
                        r["hybrid_rules_v2"] = judge(locate(k.text, hybrid2), k, dup)
                        rows.append(r)
                    print(f"{app} {size or 'default'}: {len(keys)} controls, {len(ocr)} OCR words", flush=True)
            finally:
                win.GetWindowPattern().Close()   # ORION's own window (blank, nothing to save)
    conds = ["hybrid_learned", "hybrid_rules", "ocr_learned", "ocr_rules", "uia_rules",
             "hybrid_learned_v2", "hybrid_rules_v2"]

    def summary(sel):
        out = {"n": len(sel)}
        for c in conds:
            cnt = Counter(r[c] for r in sel)
            out[c] = {k: round(100 * cnt[k] / max(len(sel), 1), 1) for k in ("correct", "wrong", "abstain")}
        return out

    report = {
        "protocol": "research/eval_real/eval_real_apps.py docstring", "date": time.strftime("%Y-%m-%d"),
        "model": {"tau": bundle["tau"], "margin": bundle.get("margin")},
        "all": summary(rows),
        "visible_text_only": summary([r for r in rows if r["visible_text"]]),
        "by_app": {a: summary([r for r in rows if r["app"] == a]) for a in APPS},
        "rows": rows,
    }
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    for k in ("all", "visible_text_only"):
        print(k, json.dumps(report[k]))
    for a in APPS:
        print(a, json.dumps(report["by_app"][a]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
