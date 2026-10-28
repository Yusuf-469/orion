"""Headless smoke test of an installed ORION (`orion --selftest`): no windows, temp folder only.

Checks that the parts a fresh install needs are present and work: planning + file tools + verification,
the safety layer, the browser tools (Playwright Chromium), local OCR, UI Automation and the grounding model.
Writes JSON results; exit code 0 only if every required check passed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import traceback
from pathlib import Path


def _plan_and_run(goal: str, ws: Path, granted=None):
    from orion.app.main_window import build_registry
    from orion.config import OrionConfig
    from orion.execution.runtime import ToolRuntime
    from orion.memory import TaskStore
    from orion.orchestration.cancel import KillSwitch
    from orion.orchestration.graph_runner import GraphRunner
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.verification import Verifier
    policy = PolicyEngine(frozenset(granted or OrionConfig().granted_permissions))
    rt = ToolRuntime(build_registry(), policy, DenyAllConfirmer(), ws)
    res = plan_request(TemplatePlanner(), goal, rt.registry, policy, ws)
    if res.status != "ok":
        return res.status, None
    store = TaskStore(ws.parent / "selftest.db")
    try:
        gr = GraphRunner(store, KillSwitch(), rt, Verifier(ws))
        tid = gr.create(res.goal, res.plan, "template", False)
        out = str(gr.run(tid, KillSwitch().new_token(), False))
        if out != "verified_complete":   # say why, so a broken install can be fixed
            out += ": " + "; ".join(s["evidence"] or "" for s in store.list_steps(tid) if s["status"] != "succeeded")
        return res.status, out
    finally:
        store.close()


def check_files(ws: Path) -> str:
    status, out = _plan_and_run('create a file notes.txt containing "selftest" then copy notes.txt to '
                                'backup/notes.txt', ws)
    assert out == "verified_complete", (status, out)
    assert (ws / "backup" / "notes.txt").read_text(encoding="utf-8") == "selftest"
    return "planned, ran and verified a 2-step file task"


def check_safety(ws: Path) -> str:
    (ws / "keep.txt").write_text("keep", encoding="utf-8")
    status, out = _plan_and_run("delete keep.txt", ws)
    assert status == "invalid" and (ws / "keep.txt").exists(), (status, out)
    status, _ = _plan_and_run('create a file ..\\outside.txt containing "x"', ws)
    assert status == "invalid" and not (ws.parent / "outside.txt").exists(), status
    return "delete without permission and writing outside the workspace were both refused"


def check_browser(ws: Path) -> str:
    from orion.app.main_window import install_demo_pages
    install_demo_pages(ws)
    status, out = _plan_and_run("save the table from sales.html as report.csv then summarize report.csv "
                                "into summary.txt", ws)
    assert out == "verified_complete", (status, out)
    assert "Rows: 5" in (ws / "summary.txt").read_text(encoding="utf-8")
    return "read the demo page's table in Chromium, wrote and summarized a CSV"


def check_ocr(ws: Path) -> str:
    from PIL import Image, ImageDraw, ImageFont

    from orion.grounding.screen import _ocr_engine
    img = Image.new("RGB", (360, 90), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((20, 20), "Export Report", fill="black", font=font)
    import numpy as np
    result, _ = _ocr_engine()(np.array(img))
    texts = [r[1] for r in result or []]
    assert any("Export" in t for t in texts), texts
    return f"local OCR read {texts}"


def check_uia(ws: Path) -> str:
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        n = len(auto.GetRootControl().GetChildren())
    return f"UI Automation works ({n} top-level windows visible; none were read or touched)"


def check_grounding(ws: Path) -> str:
    from orion.grounding.features import MODEL_PATH, load_model
    b = load_model()
    return f"learned scorer loaded ({MODEL_PATH.name})" if b else "learned scorer missing: rule-based grounding is used"


CHECKS = [("files_plan_verify", check_files, True), ("safety_layer", check_safety, True),
          ("browser", check_browser, True), ("ocr", check_ocr, True), ("ui_automation", check_uia, True),
          ("grounding_model", check_grounding, False)]


def run_selftest(out: Path) -> int:
    results, all_ok = {}, True
    tmp = Path(tempfile.mkdtemp(prefix="orion-selftest-"))
    try:
        for name, fn, required in CHECKS:
            ws = tmp / name / "workspace"
            ws.mkdir(parents=True)
            t0 = time.monotonic()
            try:
                results[name] = {"ok": True, "detail": fn(ws)}
            except Exception as e:   # report, never crash: the point is to show what is missing
                hint = " (run ORION --install-browser once)" if name == "browser" and "Executable" in str(e) else ""
                results[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"[:400] + hint,
                                 "trace": traceback.format_exc()[-1200:]}
                all_ok = all_ok and not required
            results[name]["seconds"] = round(time.monotonic() - t0, 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    from orion import resources
    report = {"ok": all_ok, "frozen": resources.FROZEN, "checks": results,
              "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v["ok"] for k, v in results.items()} | {"ok": all_ok}))
    return 0 if all_ok else 1
