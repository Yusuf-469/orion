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
    deadline = time.monotonic() + 5
    while canvas_open() and time.monotonic() < deadline:   # closing is asynchronous; don't leak into the next test
        time.sleep(0.1)
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


class Picker:
    """Answers 'which one did you mean?' with the option mentioning `where`."""
    def __init__(self, where):
        self.where, self.asked = where, []

    def confirm(self, req, token):
        return False

    def choose(self, req, options, token):
        self.asked.append(options)
        return next((i for i, o in enumerate(options) if self.where in o), None)


def open_duplicate_layout(ws):
    """Two buttons labelled Export: the top middle one (logs 'Export #1') and the centre one ('Export #2')."""
    import subprocess
    from pathlib import Path
    app = Path(__file__).resolve().parents[2] / "demo" / "apps" / "canvas_buttons.py"
    exe = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(exe), str(app), str(ws / "canvas_clicks.log"), "+200+200", "duplicate"])
    deadline = time.monotonic() + 15
    while not canvas_open():
        assert time.monotonic() < deadline, "demo app did not open"
        time.sleep(0.2)


@pytest.mark.parametrize("pick,expect", [("centre", "clicked Export #2"), ("top middle", "clicked Export #1")])
def test_two_matches_ask_the_user_and_click_the_chosen_one(orion, pick, expect):
    from orion.planner.schemas import Outcome
    from orion.recovery import RecoveryEngine
    gr, store, ws = orion
    p = Picker(pick)
    gr.recovery = RecoveryEngine(gr.runtime, p)
    open_duplicate_layout(ws)
    tid, out = run(orion, "click Export in the canvas demo")
    steps = store.list_steps(tid)
    assert out is Outcome.VERIFIED_COMPLETE, [s["evidence"] for s in steps]
    assert len(p.asked) == 1 and len(p.asked[0]) == 2
    assert "the one you chose" in steps[-1]["evidence"]
    clicks = (ws / "canvas_clicks.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(clicks) == 1 and clicks[0].endswith(expect), clicks
    print("\n  asked:", p.asked[0], "\n  ", steps[-1]["evidence"])


def test_two_matches_and_no_answer_clicks_nothing(orion):
    from orion.planner.schemas import Outcome
    from orion.policy import DenyAllConfirmer
    from orion.recovery import RecoveryEngine
    gr, store, ws = orion
    gr.recovery = RecoveryEngine(gr.runtime, DenyAllConfirmer())
    open_duplicate_layout(ws)
    tid, out = run(orion, "click Export in the canvas demo")
    step = store.list_steps(tid)[-1]
    assert out is not Outcome.VERIFIED_COMPLETE and step["status"] == "blocked", step["evidence"]
    log = ws / "canvas_clicks.log"
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_missing_button_is_not_clicked(orion):
    from orion.planner.schemas import Outcome
    gr, store, ws = orion
    tid, out = run(orion, "click Delete in the canvas demo")
    step = store.list_steps(tid)[-1]
    assert out is not Outcome.VERIFIED_COMPLETE and step["status"] == "failed"
    assert "did not click" in step["evidence"]
    log = ws / "canvas_clicks.log"
    assert not log.exists() or log.read_text(encoding="utf-8") == ""   # nothing was clicked
