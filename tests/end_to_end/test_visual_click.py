"""Visual grounding for real: click buttons that only exist as pixels (canvas demo app). Marked `real`.

The demo app logs each click to a file in the temp workspace; that is what verifies the click.
"""

import sys
import time

import pytest

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]


@pytest.fixture
def orion(tmp_path):
    import uiautomation as auto
    from orion.app.main_window import build_registry
    from orion.config import OrionConfig
    from orion.execution.runtime import ToolRuntime
    from orion.memory import TaskStore
    from orion.orchestration.cancel import KillSwitch
    from orion.orchestration.graph_runner import GraphRunner
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.verification import Verifier
    ws = tmp_path / "ws"
    ws.mkdir()
    rt = ToolRuntime(build_registry(), PolicyEngine(frozenset(OrionConfig().granted_permissions)),
                     DenyAllConfirmer(), ws)
    store = TaskStore(tmp_path / "orion.db")
    yield GraphRunner(store, KillSwitch(), rt, Verifier(ws)), store, ws
    for w in auto.GetRootControl().GetChildren():
        if w.Name == "ORION Canvas Demo":
            w.GetWindowPattern().Close()   # ORION's own demo app
    store.close()


def run(orion, goal):
    from orion.orchestration.cancel import KillSwitch
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    gr, store, ws = orion
    res = plan_request(TemplatePlanner(), goal, gr.runtime.registry, gr.runtime.policy, ws)
    assert res.status == "ok", (res.message, res.issues)
    tid = gr.create(res.goal, res.plan, "template", False)
    return tid, gr.run(tid, KillSwitch().new_token(), False)


def canvas_open():
    import uiautomation as auto
    return any(w.Name == "ORION Canvas Demo" for w in auto.GetRootControl().GetChildren())


def test_clicks_a_button_uia_cannot_see(orion):
    from orion.planner.schemas import Outcome
    gr, store, ws = orion
    tid, out = run(orion, "click Export in the canvas demo")
    steps = store.list_steps(tid)
    assert out is Outcome.VERIFIED_COMPLETE, [s["evidence"] for s in steps]
    assert "via ocr" in steps[-1]["evidence"]
    from orion.grounding.features import load_model
    assert ("learned score" if load_model() else "rules score") in steps[-1]["evidence"]
    assert (ws / "canvas_clicks.log").read_text(encoding="utf-8").strip().endswith("clicked Export")
    print("\n  ", steps[-1]["evidence"])


def test_close_report_is_not_the_window_close_button(orion):
    from orion.planner.schemas import Outcome
    gr, store, ws = orion
    tid, out = run(orion, "click Close Report in the canvas demo")
    assert out is Outcome.VERIFIED_COMPLETE, [s["evidence"] for s in store.list_steps(tid)]
    time.sleep(0.5)
    assert canvas_open(), "ORION closed the app window instead of clicking 'Close Report'"
    assert "clicked Close Report" in (ws / "canvas_clicks.log").read_text(encoding="utf-8")


def test_missing_button_is_not_clicked(orion):
    from orion.planner.schemas import Outcome
    gr, store, ws = orion
    tid, out = run(orion, "click Delete in the canvas demo")
    step = store.list_steps(tid)[-1]
    assert out is not Outcome.VERIFIED_COMPLETE and step["status"] == "failed"
    assert "did not click" in step["evidence"]
    log = ws / "canvas_clicks.log"
    assert not log.exists() or log.read_text(encoding="utf-8") == ""   # nothing was clicked
