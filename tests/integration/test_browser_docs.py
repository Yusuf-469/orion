"""Browser (headless Chromium) and CSV tools against the demo page in a temp workspace."""

import csv
import shutil
from pathlib import Path

import pytest

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.planner.service import plan_request
from orion.planner.template import TemplatePlanner
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import ErrorCode, Permission

DEMO = Path(__file__).resolve().parents[2] / "demo" / "pages" / "sales.html"


@pytest.fixture
def env(tmp_path):
    from orion.app.main_window import build_registry
    ws = tmp_path / "ws"
    (ws / "pages").mkdir(parents=True)
    shutil.copyfile(DEMO, ws / "pages" / "sales.html")
    reg = build_registry()
    return ToolRuntime(reg, PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), ws), ws


def call(rt, tool, **args):
    return rt.execute(ToolCall(tool_id=tool, args=args), CancelToken())


def test_read_table_from_demo_page(env):
    rt, _ = env
    r = call(rt, "browser.read_table", page="sales.html")
    assert r.ok, r.evidence
    assert r.output["headers"] == ["Region", "Units", "Revenue"]
    assert r.output["rows"][0] == ["North", "120", "36000"] and len(r.output["rows"]) == 5
    assert r.output["untrusted"] is True


@pytest.mark.parametrize("page", ["http://example.com/", "https://10.0.0.1/x", "file:///C:/Windows/win.ini",
                                  "..\\outside.html", "C:\\Windows\\Help\\x.html"])
def test_only_local_pages(env, page):
    rt, _ = env
    r = call(rt, "browser.read_text", page=page)
    assert not r.ok and r.error_code in (ErrorCode.PERMISSION_DENIED, ErrorCode.INVALID_INPUT)


def test_injection_text_is_returned_as_data_only(env):
    rt, ws = env
    r = call(rt, "browser.read_text", page="sales.html")
    assert r.ok and "ignore your previous instructions" in r.output["text"] and r.output["untrusted"]
    assert (ws / "pages" / "sales.html").exists()   # nothing was deleted


def test_csv_write_and_summarize(env):
    rt, ws = env
    r = call(rt, "docs.write_csv", path="out/report.csv", headers=["Region", "Units"],
             rows=[["North", "120"], ["South", "95"]])
    assert r.ok, r.evidence
    assert list(csv.reader(open(ws / "out" / "report.csv", encoding="utf-8"))) == \
        [["Region", "Units"], ["North", "120"], ["South", "95"]]
    r = call(rt, "docs.summarize_csv", src="out/report.csv", dst="out/summary.txt")
    assert r.ok, r.evidence
    text = (ws / "out" / "summary.txt").read_text(encoding="utf-8")
    assert "Rows: 2" in text and "Units: total 215" in text
    assert not call(rt, "docs.write_csv", path="out/report.csv", rows=[["x"]]).ok   # never overwrites


def test_demo_goal_plans_and_injection_cannot_change_it(env):
    rt, ws = env
    goal = ("save the table from sales.html as report.csv then summarize report.csv into summary.txt "
            "then open summary.txt in notepad")
    r = plan_request(TemplatePlanner(), goal, rt.registry, rt.policy, ws)
    assert r.status == "ok", (r.message, r.issues)
    assert [s.tool_id for s in r.plan.steps] == ["browser.read_table", "docs.write_csv", "docs.summarize_csv",
                                                 "notepad.open_file"]
    # The plan is fixed before any page is read; only headers/rows flow from the page, as data.
    assert not any("delete" in s.tool_id for s in r.plan.steps)


def test_dry_run_of_demo_goal_touches_nothing(env, tmp_path):
    from orion.memory import TaskStore
    from orion.orchestration.cancel import KillSwitch
    from orion.orchestration.graph_runner import GraphRunner
    from orion.planner.schemas import Outcome
    from orion.verification import Verifier
    rt, ws = env
    store = TaskStore(tmp_path / "t.db")
    gr = GraphRunner(store, KillSwitch(), rt, Verifier(ws))
    res = plan_request(TemplatePlanner(), "save the table from sales.html as report.csv then summarize report.csv "
                       "into summary.txt", rt.registry, rt.policy, ws)
    tid = gr.create(res.goal, res.plan, "template", True)
    assert gr.run(tid, KillSwitch().new_token(), True) is Outcome.DRY_RUN
    assert not (ws / "report.csv").exists()
    store.close()
