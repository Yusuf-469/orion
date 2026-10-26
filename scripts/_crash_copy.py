"""Helper for the acceptance run: start a goal with the app's real tools and die inside files.copy.

usage: python _crash_copy.py DATA_DIR WORKSPACE
The copy has already been written when the process exits (os._exit), so the
store shows step s2 RUNNING, like a power cut mid-action.
"""

import os
import sys
from pathlib import Path

from orion.app.main_window import build_registry
from orion.execution.runtime import ToolRuntime
from orion.memory import TaskStore
from orion.orchestration.cancel import KillSwitch
from orion.orchestration.graph_runner import GraphRunner
from orion.planner.service import plan_request
from orion.planner.template import TemplatePlanner
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.config import OrionConfig
from orion.tools.files.tools import CopyFileTool
from orion.verification import Verifier

data, ws = Path(sys.argv[1]), Path(sys.argv[2])
original = CopyFileTool.run


def crashing_run(self, args, ctx):
    original(self, args, ctx)
    os._exit(3)


CopyFileTool.run = crashing_run
reg = build_registry()
pol = PolicyEngine(frozenset(OrionConfig().granted_permissions))
store = TaskStore(data / "orion.db")
ks = KillSwitch()
gr = GraphRunner(store, ks, ToolRuntime(reg, pol, DenyAllConfirmer(), ws), Verifier(ws))
res = plan_request(TemplatePlanner(), "create a file crash.txt containing before crash then copy crash.txt to "
                   "crash_copy.txt", reg, pol, ws)
tid = gr.create(res.goal, res.plan, "template", False)
gr.run(tid, ks.new_token(), False)
print("NOT CRASHED")
