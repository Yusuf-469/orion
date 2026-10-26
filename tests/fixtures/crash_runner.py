"""Subprocess for crash tests: runs a 3-step plan and dies inside step s2.

usage: python crash_runner.py DB WORKSPACE MODE   (MODE: verifiable | unverifiable | readonly)
"""

import sys
from pathlib import Path

import crash_tools
from orion.execution.runtime import ToolRuntime
from orion.memory import TaskStore
from orion.orchestration.cancel import KillSwitch
from orion.orchestration.graph_runner import GraphRunner
from orion.planner.schemas import FileContains, FileExists, Goal, Plan, PlanStep
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import Permission, ToolRegistry
from orion.tools.files import file_tools
from orion.verification import Verifier


def build_plan(mode):
    goal = Goal(goal_id="crashgoal", request="crash test", objective="crash test",
                authorized_outputs=["a.txt", "b.txt", "c.txt"],
                completion_checks=[FileContains(path="a.txt", text="one"), FileContains(path="c.txt", text="three")])
    s2_tool = "test.crash_read" if mode == "readonly" else "test.crash_write"
    s2_post = [FileExists(path="b.txt")] if mode == "verifiable" else []
    steps = [
        PlanStep(id="s1", description="write a", tool_id="files.write_new",
                 args={"path": "a.txt", "content": "one"}, postconditions=[FileContains(path="a.txt", text="one")]),
        PlanStep(id="s2", description="crashing step", tool_id=s2_tool, args={"path": "b.txt"},
                 depends_on=["s1"], postconditions=s2_post),
        PlanStep(id="s3", description="write c", tool_id="files.write_new",
                 args={"path": "c.txt", "content": "three"}, depends_on=["s2"],
                 postconditions=[FileContains(path="c.txt", text="three")]),
    ]
    return goal, Plan(goal_id=goal.goal_id, steps=steps)


def registry(crash):
    reg = ToolRegistry()
    for t in file_tools():
        reg.register(t)
    for cls in (crash_tools.CrashWriteTool, crash_tools.CrashReadTool):
        t = cls()
        t.crash = crash
        reg.register(t)
    return reg


if __name__ == "__main__":
    db, ws, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    store = TaskStore(db)
    ks = KillSwitch()
    rt = ToolRuntime(registry(crash=True), PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), ws)
    gr = GraphRunner(store, ks, rt, Verifier(ws))
    goal, plan = build_plan(mode)
    tid = gr.create(goal, plan, "test", dry_run=False)
    gr.run(tid, ks.new_token(), dry_run=False)
    print("NOT CRASHED")   # reaching here means the crash did not happen
