"""First end-to-end slice, for real: browser -> CSV -> summary -> Notepad, verified on disk and on screen.

Marked `real`: opens Chromium (headless) and Notepad. Temp workspace only. Closes only its own Notepad
tab, plus the Notepad window if none was open before the test.
"""

import csv
import shutil
import sys
from pathlib import Path

import pytest

import uuid

P = f"orion-test-{uuid.uuid4().hex[:6]}"   # unique: never collides with the user's tabs or old runs
SUMMARY, NOTE = f"{P}-summary.txt", f"{P}-note.txt"

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

DEMO = Path(__file__).resolve().parents[2] / "demo" / "pages" / "sales.html"


@pytest.fixture
def orion(tmp_path):
    import uiautomation as auto
    from orion.app.main_window import build_registry
    from orion.config import OrionConfig
    from orion.execution.runtime import ToolCall, ToolRuntime
    from orion.memory import TaskStore
    from orion.orchestration.cancel import CancelToken, KillSwitch
    from orion.orchestration.graph_runner import GraphRunner
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.verification import Verifier

    had_window = any(w.ClassName == "Notepad" for w in auto.GetRootControl().GetChildren())
    ws = tmp_path / "workspace"
    (ws / "pages").mkdir(parents=True)
    shutil.copyfile(DEMO, ws / "pages" / "sales.html")
    reg = build_registry()
    rt = ToolRuntime(reg, PolicyEngine(frozenset(OrionConfig().granted_permissions)), DenyAllConfirmer(), ws)
    store = TaskStore(tmp_path / "orion.db")
    ks = KillSwitch()
    gr = GraphRunner(store, ks, rt, Verifier(ws))
    yield gr, store, ks, ws
    for f in (SUMMARY, NOTE):
        rt.execute(ToolCall(tool_id="notepad.close_tab", args={"path": f}), CancelToken())
    if not had_window:
        for w in auto.GetRootControl().GetChildren():
            if w.ClassName == "Notepad":
                w.GetWindowPattern().Close()
    store.close()


def run_goal(orion, text):
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    gr, store, ks, ws = orion
    res = plan_request(TemplatePlanner(), text, gr.runtime.registry, gr.runtime.policy, ws)
    assert res.status == "ok", (res.message, res.issues)
    tid = gr.create(res.goal, res.plan, "template", False)
    return tid, gr.run(tid, ks.new_token(), False)


def test_demo_slice_table_to_notepad(orion):
    from orion.planner.schemas import Outcome
    gr, store, ks, ws = orion
    tid, outcome = run_goal(orion, "save the table from sales.html as report.csv then summarize report.csv "
                                   f"into {SUMMARY} then open {SUMMARY} in notepad")
    steps = {s["step_key"]: s for s in store.list_steps(tid)}
    assert outcome is Outcome.VERIFIED_COMPLETE, {k: (s["status"], s["evidence"]) for k, s in steps.items()}
    rows = list(csv.reader(open(ws / "report.csv", encoding="utf-8")))
    assert rows[0] == ["Region", "Units", "Revenue"] and len(rows) == 6
    summary = (ws / SUMMARY).read_text(encoding="utf-8")
    assert "Rows: 5" in summary and "Revenue: total 163500" in summary
    assert "screen matches disk" in steps["s4"]["evidence"]
    print("\n" + "\n".join(f"  {k}: {s['evidence'][:150]}" for k, s in steps.items()))


def test_type_into_notepad_and_save(orion):
    from orion.planner.schemas import Outcome
    gr, store, ks, ws = orion
    (ws / NOTE).write_text("old text", encoding="utf-8")
    tid, outcome = run_goal(orion, f'type "Meeting moved to 4 pm" into {NOTE} in notepad')
    assert outcome is Outcome.VERIFIED_COMPLETE, [s["evidence"] for s in store.list_steps(tid)]
    assert (ws / NOTE).read_text(encoding="utf-8-sig").strip() == "Meeting moved to 4 pm"
    assert (ws / ".orion_backups").is_dir()
