"""Graph runner: multi-step state, verification, outcomes, checkpoints, cancel, migration, crash/resume.

File effects happen only in pytest's tmp workspace.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from orion.execution.runtime import ToolRuntime
from orion.memory import TaskStore
from orion.memory.store import _SCHEMA
from orion.orchestration.cancel import KillSwitch
from orion.orchestration.graph_runner import GraphRunner
from orion.planner.schemas import FileContains, FileExists, Goal, Outcome, Plan, PlanStep
from orion.planner.service import plan_request
from orion.planner.template import TemplatePlanner
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import Permission, ToolRegistry
from orion.tools.files import TRASH_DIR, file_tools
from orion.verification import Verifier

FIXTURES = Path(__file__).parent.parent / "fixtures"
sys.path.insert(0, str(FIXTURES))
import crash_runner  # noqa: E402
import crash_tools  # noqa: E402

ALL = frozenset(Permission)


class Approve:
    def confirm(self, req, token):
        return True


@pytest.fixture
def env(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = TaskStore(tmp_path / "t.db")
    ks = KillSwitch()

    def make(confirmer=None, registry=None):
        reg = registry
        if reg is None:
            reg = ToolRegistry()
            for t in file_tools():
                reg.register(t)
        rt = ToolRuntime(reg, PolicyEngine(ALL), confirmer or DenyAllConfirmer(), ws)
        return GraphRunner(store, ks, rt, Verifier(ws))

    yield store, ks, ws, make
    store.close()


def run_request(env, request, confirmer=None, dry_run=False):
    store, ks, ws, make = env
    gr = make(confirmer)
    res = plan_request(TemplatePlanner(), request, gr.runtime.registry, gr.runtime.policy, ws)
    assert res.status == "ok", (res.status, res.message, res.issues)
    tid = gr.create(res.goal, res.plan, "template", dry_run)
    return gr, tid, gr.run(tid, ks.new_token(), dry_run)


def statuses(store, tid):
    return {s["step_key"]: s["status"] for s in store.list_steps(tid)}


def test_two_step_plan_verified_complete(env):
    store, _, ws, _ = env
    _, tid, out = run_request(env, "create a file a.txt containing hello then copy a.txt to b.txt")
    assert out is Outcome.VERIFIED_COMPLETE
    assert statuses(store, tid) == {"s1": "succeeded", "s2": "succeeded"}
    assert (ws / "b.txt").read_text() == "hello"
    t = store.get_task(tid)
    assert t["status"] == "succeeded" and t["outcome"] == "verified_complete"
    assert "verified:" in store.list_steps(tid)[1]["evidence"]


def test_reference_passes_output_between_steps(env):
    store, _, ws, _ = env
    (ws / "src.txt").write_text("from source")
    _, tid, out = run_request(env, "put the contents of src.txt into out.txt")
    assert out is Outcome.VERIFIED_COMPLETE and (ws / "out.txt").read_text() == "from source"


def test_move_declined_is_partially_complete(env):
    store, _, ws, _ = env
    (ws / "r.txt").write_text("x")
    _, tid, out = run_request(env, "move r.txt to archive/r.txt")
    assert out is Outcome.PARTIALLY_COMPLETE
    assert statuses(store, tid) == {"s1": "succeeded", "s2": "blocked"}
    assert (ws / "r.txt").exists() and (ws / "archive" / "r.txt").exists()


def test_move_confirmed_checkpoints_before_delete(env):
    store, _, ws, _ = env
    (ws / "r.txt").write_text("x")
    _, tid, out = run_request(env, "move r.txt to archive/r.txt", confirmer=Approve())
    assert out is Outcome.VERIFIED_COMPLETE
    assert not (ws / "r.txt").exists() and len(list((ws / TRASH_DIR).iterdir())) == 1
    cps = store.list_checkpoints(tid)
    assert len(cps) == 1 and "before s2" in cps[0]["label"] and '"s1": "succeeded"' in cps[0]["snapshot"]


def test_failed_step_skips_dependents(env):
    store, _, ws, _ = env
    (ws / "a.txt").write_text("already here")
    _, tid, out = run_request(env, "create a file a.txt containing new then copy a.txt to b.txt")
    assert statuses(store, tid) == {"s1": "failed", "s2": "skipped"}
    assert out is Outcome.FAILED and not (ws / "b.txt").exists()


def test_postcondition_failure_is_not_success(env):
    store, ks, ws, make = env
    gr = make()
    goal = Goal(request="r", objective="o", authorized_outputs=["a.txt"],
                completion_checks=[FileExists(path="a.txt")])
    plan = Plan(goal_id=goal.goal_id, steps=[PlanStep(
        id="s1", description="w", tool_id="files.write_new", args={"path": "a.txt", "content": "real"},
        postconditions=[FileContains(path="a.txt", text="something else")])])
    tid = gr.create(goal, plan, "test", False)
    out = gr.run(tid, ks.new_token(), False)
    step = store.list_steps(tid)[0]
    assert step["status"] == "failed" and "verification_failed" in step["evidence"]
    # the goal's own check passes (file exists), so the outcome reflects the goal, with the step failure on record
    assert out is Outcome.VERIFIED_COMPLETE


def test_dry_run_changes_nothing(env):
    store, _, ws, _ = env
    _, tid, out = run_request(env, "create a file a.txt containing hi then copy a.txt to b.txt", dry_run=True)
    assert out is Outcome.DRY_RUN and list(ws.iterdir()) == []
    assert all("would allow" in s["evidence"] for s in store.list_steps(tid))


def test_no_completion_checks_is_unverified(env):
    store, _, _, _ = env
    _, tid, out = run_request(env, "list files")
    assert out is Outcome.UNVERIFIED and store.get_task(tid)["status"] == "needs_review"


def test_cancel_stops_remaining_steps(env):
    store, ks, ws, make = env
    gr = make()
    res = plan_request(TemplatePlanner(), "create a file a.txt containing 1 then copy a.txt to b.txt",
                       gr.runtime.registry, gr.runtime.policy, ws)
    tid = gr.create(res.goal, res.plan, "template", False)
    token = ks.new_token()
    gr.on_event = lambda e: token.cancel("test") if e["kind"] == "step_done" else None
    assert gr.run(tid, token, False) is Outcome.CANCELLED
    assert statuses(store, tid) == {"s1": "succeeded", "s2": "cancelled"}
    assert not (ws / "b.txt").exists()


def test_read_only_steps_run_first(env):
    store, ks, ws, make = env
    (ws / "x.txt").write_text("x")
    gr = make()
    goal = Goal(request="r", objective="o", authorized_outputs=["n.txt"], completion_checks=[])
    plan = Plan(goal_id=goal.goal_id, steps=[
        PlanStep(id="w", description="w", tool_id="files.write_new", args={"path": "n.txt", "content": "1"}),
        PlanStep(id="r", description="r", tool_id="files.read", args={"path": "x.txt"}),
    ])
    tid = gr.create(goal, plan, "test", False)
    gr.run(tid, ks.new_token(), False)
    assert [k for _, k, _ in gr.executed] == ["r", "w"]


def test_v1_database_migrates_and_keeps_history(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(_SCHEMA)
    con.execute("INSERT INTO meta VALUES ('schema_version','1')")
    con.execute("INSERT INTO tasks(title,status,dry_run,created_at,updated_at) VALUES ('old','succeeded',0,0,0)")
    con.commit()
    con.close()
    store = TaskStore(db)
    assert store.schema_version() == 2
    assert store.list_tasks()[0]["title"] == "old"
    assert "outcome" in store.get_task(1)
    store.close()


def test_history_delete(env):
    store, _, _, _ = env
    _, tid, _ = run_request(env, "list files")
    store.delete_task(tid)
    assert store.list_tasks() == [] and store.list_steps(tid) == [] and store.load_plan(tid) is None


# --- crash and resume (real subprocess crash) -------------------------------------------

def crash(tmp_path, mode):
    db, ws = tmp_path / "crash.db", tmp_path / "cws"
    ws.mkdir()
    p = subprocess.run([sys.executable, str(FIXTURES / "crash_runner.py"), str(db), str(ws), mode],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 3, f"expected crash exit 3, got {p.returncode}: {p.stdout} {p.stderr}"
    return db, ws


def resume(db, ws):
    crash_tools.CrashWriteTool.calls = crash_tools.CrashReadTool.calls = 0
    store = TaskStore(db)
    ks = KillSwitch()
    rt = ToolRuntime(crash_runner.registry(crash=False), PolicyEngine(ALL), DenyAllConfirmer(), ws)
    gr = GraphRunner(store, ks, rt, Verifier(ws))
    [task] = store.interrupted_tasks()
    assert statuses(store, task["id"]) == {"s1": "succeeded", "s2": "running", "s3": "pending"}
    out = gr.resume(task["id"], ks.new_token())
    return store, gr, task["id"], out


def test_resume_verifiable_step_is_verified_not_repeated(tmp_path):
    db, ws = crash(tmp_path, "verifiable")
    store, gr, tid, out = resume(db, ws)
    assert crash_tools.CrashWriteTool.calls == 0, "interrupted non-read-only step was repeated"
    assert [k for _, k, _ in gr.executed] == ["s3"], "completed step s1 was repeated"
    s2 = next(s for s in store.list_steps(tid) if s["step_key"] == "s2")
    assert s2["status"] == "succeeded" and s2["evidence"].startswith("verified after resume")
    assert out is Outcome.VERIFIED_COMPLETE
    store.close()


def test_resume_unverifiable_step_needs_review_not_repeated(tmp_path):
    db, ws = crash(tmp_path, "unverifiable")
    store, gr, tid, out = resume(db, ws)
    assert crash_tools.CrashWriteTool.calls == 0 and gr.executed == []
    assert statuses(store, tid) == {"s1": "succeeded", "s2": "needs_review", "s3": "skipped"}
    assert "NOT repeated" in next(s for s in store.list_steps(tid) if s["step_key"] == "s2")["evidence"]
    assert out is Outcome.PARTIALLY_COMPLETE
    store.close()


def test_resume_read_only_step_is_rerun(tmp_path):
    db, ws = crash(tmp_path, "readonly")
    store, gr, tid, out = resume(db, ws)
    assert crash_tools.CrashReadTool.calls == 1
    assert [k for _, k, _ in gr.executed] == ["s2", "s3"]
    assert out is Outcome.VERIFIED_COMPLETE
    store.close()
