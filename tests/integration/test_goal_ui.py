"""Goal box, resume banner and history controls, offscreen. Files stay in pytest's tmp workspace."""

import time

import pytest

from orion.config import OrionConfig
from orion.memory import TaskStore
from orion.orchestration.states import Status

pytestmark = [pytest.mark.ui]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def _pump(qapp, seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if until and until():
            return True
        time.sleep(0.005)
    return bool(until and until())


@pytest.fixture
def make_window(qapp, tmp_path):
    from orion.app.main_window import MainWindow
    made = []

    def make(dry_run=False, store=None):
        cfg = OrionConfig(data_dir=tmp_path, workspace_dir=tmp_path / "workspace", dry_run_default=dry_run)
        store = store or TaskStore(cfg.db_path)
        w = MainWindow(cfg, store, register_hotkey=False)
        w.show()
        made.append((w, store))
        return w

    yield make
    for w, store in made:
        w.close()
        store.close()


def goal(qapp, w, text):
    w.goal_input.setText(text)
    tid = w.start_goal()
    if tid is not None:
        _pump(qapp, 5, until=lambda: w.store.get_task(tid)["outcome"] is not None)
        _pump(qapp, 0.1)
    return tid


def test_goal_runs_and_is_verified(qapp, make_window):
    w = make_window()
    tid = goal(qapp, w, "create a file notes.txt containing hello then copy notes.txt to backup/notes.txt")
    assert w.store.get_task(tid)["outcome"] == "verified_complete"
    assert (w.cfg.workspace_dir / "backup" / "notes.txt").read_text() == "hello"
    assert "VERIFIED_COMPLETE" in w.info_label.text()
    assert w.table.item(0, 4).text() == "verified_complete"


def test_dry_run_goal_previews_every_step(qapp, make_window):
    w = make_window(dry_run=True)
    tid = goal(qapp, w, "create a file a.txt containing x then copy a.txt to b.txt")
    assert w.store.get_task(tid)["outcome"] == "dry_run"
    assert not (w.cfg.workspace_dir / "a.txt").exists()
    assert [s["status"] for s in w.store.list_steps(tid)] == ["skipped", "skipped"]


def test_clarification_asks_and_creates_no_task(qapp, make_window):
    w = make_window()
    assert goal(qapp, w, "copy report.txt") is None
    assert "Where should the copy" in w.info_label.text()
    assert w.store.list_tasks() == []


def test_unsupported_and_invalid_goals_create_no_task(qapp, make_window):
    w = make_window()
    assert goal(qapp, w, "send an email to my boss") is None
    assert "does not understand" in w.error_label.text()
    assert goal(qapp, w, "create a file ..\\x.txt containing y") is None
    assert "Plan rejected" in w.error_label.text() and "outside_workspace" in w.error_label.text()
    assert w.store.list_tasks() == []


def test_interrupted_task_banner_and_resume(qapp, make_window, tmp_path):
    from orion.execution.runtime import ToolRuntime
    from orion.orchestration.cancel import KillSwitch
    from orion.orchestration.graph_runner import GraphRunner
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.app.main_window import build_registry
    from orion.verification import Verifier

    ws = tmp_path / "workspace"
    ws.mkdir()
    store = TaskStore(tmp_path / "orion.db")
    reg, pol = build_registry(), PolicyEngine(frozenset(OrionConfig().granted_permissions))
    gr = GraphRunner(store, KillSwitch(), ToolRuntime(reg, pol, DenyAllConfirmer(), ws), Verifier(ws))
    res = plan_request(TemplatePlanner(), "create a file a.txt containing hi then copy a.txt to b.txt", reg, pol, ws)
    tid = gr.create(res.goal, res.plan, "template", False)
    # Simulate a crash right after s1's file was written but before its result was recorded.
    store.set_task_status(tid, Status.READY)
    store.set_task_status(tid, Status.RUNNING)
    s1 = store.list_steps(tid)[0]
    store.set_step_status(s1["id"], Status.READY)
    store.mark_step_started(s1["id"], "crashed-action")
    (ws / "a.txt").write_text("hi")

    w = make_window(store=store)
    assert not w.resume_row.isHidden() and "interrupted" in w.resume_label.text()
    w.resume_btn.click()
    assert _pump(qapp, 5, until=lambda: store.get_task(tid)["outcome"] is not None)
    assert store.get_task(tid)["outcome"] == "verified_complete"
    assert store.list_steps(tid)[0]["evidence"].startswith("verified after resume")
    assert (ws / "a.txt").read_text() == "hi"   # not rewritten


def _fake_llm(w, request_file="n.txt", content="hi"):
    import json as _json
    from orion.planner.llm import LLMPlanner
    reply = _json.dumps({"goal": {"objective": "note"},
                         "plan": {"steps": [{"id": "w", "description": "write", "tool_id": "files.write_new",
                                             "args": {"path": request_file, "content": content},
                                             "postconditions": [{"kind": "file_contains", "path": request_file,
                                                                 "text": content}]}]}})
    w.planner = LLMPlanner(lambda prompt: reply, w.registry, w.policy, w.cfg.workspace_dir)


@pytest.mark.parametrize("accept", [True, False])
def test_llm_plan_requires_review(qapp, make_window, monkeypatch, accept):
    w = make_window()
    _fake_llm(w)
    reviewed = []
    monkeypatch.setattr(w, "_review_plan", lambda res: reviewed.append(res) or accept)
    w.goal_input.setText("make a note n.txt containing hi")
    assert w.start_goal() is None               # planning happens off the UI thread
    assert _pump(qapp, 5, until=lambda: reviewed and w.goal_btn.isEnabled())
    if accept:
        assert _pump(qapp, 5, until=lambda: w.last_goal_task is not None and
                     w.store.get_task(w.last_goal_task)["outcome"] is not None)
        assert w.store.get_task(w.last_goal_task)["outcome"] == "verified_complete"
        assert (w.cfg.workspace_dir / "n.txt").read_text() == "hi"
    else:
        _pump(qapp, 0.3)
        assert w.store.list_tasks() == [] and not (w.cfg.workspace_dir / "n.txt").exists()
        assert "declined" in w.info_label.text()
    assert reviewed[0].planner == "llm"


def test_invented_llm_content_never_reaches_review(qapp, make_window, monkeypatch):
    w = make_window()
    _fake_llm(w, content="something the user never said")
    monkeypatch.setattr(w, "_review_plan", lambda res: pytest.fail("invalid plan must not be offered for review"))
    w.goal_input.setText("make a note n.txt")
    w.start_goal()
    assert _pump(qapp, 5, until=lambda: "Plan rejected" in w.error_label.text())
    assert "intent_drift" in w.error_label.text() and w.store.list_tasks() == []


def test_template_plans_do_not_need_review(qapp, make_window, monkeypatch):
    w = make_window()
    monkeypatch.setattr(w, "_review_plan", lambda res: pytest.fail("template plans are not reviewed"))
    assert goal(qapp, w, "list files") is not None


def test_history_delete_and_clear(qapp, make_window, monkeypatch):
    w = make_window()
    t1 = goal(qapp, w, "list files")
    t2 = goal(qapp, w, "list files")
    monkeypatch.setattr(w, "_ask_yes_no", lambda *a: True)
    w.table.selectRow(1)   # newest first: row 1 is t1
    w.delete_selected_history()
    assert [t["id"] for t in w.store.list_tasks()] == [t2]
    w.clear_history()
    assert w.store.list_tasks() == []
    assert t1 != t2


def test_history_delete_declined_keeps_everything(qapp, make_window, monkeypatch):
    w = make_window()
    goal(qapp, w, "list files")
    monkeypatch.setattr(w, "_ask_yes_no", lambda *a: False)
    w.clear_history()
    assert len(w.store.list_tasks()) == 1
