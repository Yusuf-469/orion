"""Recovery from real mid-task problems in Notepad (marked `real`). Temp workspace only.

Problems are injected right after ORION opens its file and before it types:
  A/B: an "Open" dialog pops up over Notepad (approve / decline closing it)
  C:   another file takes over the active tab
"""

import subprocess
import sys
import time

import pytest

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

import uuid

P = f"orion-test-{uuid.uuid4().hex[:6]}"   # unique names: never collide with the user's tabs or old runs
NOTE, OTHER = f"{P}-note.txt", f"{P}-other.txt"
GOAL = f'type "Updated by ORION" into {NOTE} in notepad'


class Confirmer:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def confirm(self, req, token):
        self.asked.append(req)
        return self.answer


@pytest.fixture
def make(tmp_path):
    import uiautomation as auto
    from orion.app.main_window import build_registry
    from orion.config import OrionConfig
    from orion.execution.runtime import ToolCall, ToolRuntime
    from orion.memory import TaskStore
    from orion.orchestration.cancel import CancelToken, KillSwitch
    from orion.orchestration.graph_runner import GraphRunner
    from orion.policy import PolicyEngine
    from orion.recovery import RecoveryEngine
    from orion.tools.windows.notepad import blocking_dialog, close_dialog
    from orion.verification import Verifier

    had_window = any(w.ClassName == "Notepad" for w in auto.GetRootControl().GetChildren())
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / NOTE).write_text("old text", encoding="utf-8")
    (ws / OTHER).write_text("other file", encoding="utf-8")
    made = {}

    def build(confirmer):
        rt = ToolRuntime(build_registry(), PolicyEngine(frozenset(OrionConfig().granted_permissions)),
                         confirmer, ws)
        store = TaskStore(tmp_path / "orion.db")
        gr = GraphRunner(store, KillSwitch(), rt, Verifier(ws), recovery=RecoveryEngine(rt, confirmer))
        made.update(rt=rt, store=store)
        return gr, store, ws

    yield build
    for w in auto.GetRootControl().GetChildren():   # remove any dialog left by a declined recovery
        if w.ClassName == "Notepad":
            d = blocking_dialog(w.NativeWindowHandle)
            if d:
                close_dialog(d[0])
    for f in (NOTE, OTHER):
        made["rt"].execute(ToolCall(tool_id="notepad.close_tab", args={"path": f}), CancelToken())
    if not had_window:
        for w in auto.GetRootControl().GetChildren():
            if w.ClassName == "Notepad":
                w.GetWindowPattern().Close()
    made["store"].close()


def run(gr, ws, inject):
    from orion.orchestration.cancel import KillSwitch
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    res = plan_request(TemplatePlanner(), GOAL, gr.runtime.registry, gr.runtime.policy, ws)
    assert res.status == "ok", res.issues
    tid = gr.create(res.goal, res.plan, "template", False)
    original = gr.on_event

    def hook(e):
        original(e)
        if e["kind"] == "step_done" and e["message"].startswith("s1"):
            inject()
    gr.on_event = hook
    return tid, gr.run(tid, KillSwitch().new_token(), False)


def open_dialog_over_notepad():
    import uiautomation as auto
    from orion.tools.windows.notepad import blocking_dialog
    with auto.UIAutomationInitializerInThread():
        win = next(w for w in auto.GetRootControl().GetChildren()
                   if w.ClassName == "Notepad" and w.Name.lstrip("*").startswith(NOTE))
        win.DocumentControl(searchDepth=12).SendKeys("{Ctrl}o")
        for _ in range(30):
            if blocking_dialog(win.NativeWindowHandle):
                return
            time.sleep(0.1)
    raise AssertionError("could not open a dialog over Notepad")


def switch_tab_to_other_file(ws):
    import uiautomation as auto
    subprocess.Popen([r"C:\Windows\System32\notepad.exe", str(ws / OTHER)])
    with auto.UIAutomationInitializerInThread():
        for _ in range(50):
            if any(w.ClassName == "Notepad" and w.Name.startswith(OTHER)
                   for w in auto.GetRootControl().GetChildren()):
                return
            time.sleep(0.1)
    raise AssertionError(f"{OTHER} did not become the active tab")


def test_dialog_closed_with_approval_then_task_completes(make):
    from orion.planner.schemas import Outcome
    conf = Confirmer(True)
    gr, store, ws = make(conf)
    tid, outcome = run(gr, ws, open_dialog_over_notepad)
    s2 = store.list_steps(tid)[1]
    assert outcome is Outcome.VERIFIED_COMPLETE, [s["evidence"] for s in store.list_steps(tid)]
    assert "recovered (closed the" in s2["evidence"]
    assert len(conf.asked) == 1 and "blocking Notepad" in conf.asked[0].action
    assert (ws / NOTE).read_text(encoding="utf-8-sig").strip() == "Updated by ORION"


def test_dialog_declined_stops_safely_file_untouched(make):
    from orion.planner.schemas import Outcome
    gr, store, ws = make(Confirmer(False))
    tid, outcome = run(gr, ws, open_dialog_over_notepad)
    s2 = store.list_steps(tid)[1]
    assert s2["status"] == "blocked" and "chose not to close" in s2["evidence"]
    assert outcome in (Outcome.PARTIALLY_COMPLETE, Outcome.BLOCKED)
    assert (ws / NOTE).read_text(encoding="utf-8") == "old text"


def test_tab_switched_mid_task_is_recovered(make):
    from orion.planner.schemas import Outcome
    conf = Confirmer(True)
    gr, store, ws = make(conf)
    tid, outcome = run(gr, ws, lambda: switch_tab_to_other_file(ws))
    s2 = store.list_steps(tid)[1]
    assert outcome is Outcome.VERIFIED_COMPLETE, [s["evidence"] for s in store.list_steps(tid)]
    assert "recovered (" in s2["evidence"] and conf.asked == []   # no question needed for a tab switch
    assert (ws / OTHER).read_text(encoding="utf-8") == "other file"   # the other file was not touched
