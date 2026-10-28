"""Form filling stops before submit. Planner checks are offline; the fill itself is `real` (visible window)."""

import shutil
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[2] / "demo" / "pages"


@pytest.fixture
def env(tmp_path):
    from orion.app.main_window import build_registry
    from orion.execution.runtime import ToolRuntime
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.tools import Permission
    ws = tmp_path / "ws"
    (ws / "pages").mkdir(parents=True)
    shutil.copyfile(DEMO / "signup.html", ws / "pages" / "signup.html")
    return ToolRuntime(build_registry(), PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), ws), ws


GOAL = 'fill the form on signup.html with name "Asha Rao" email "asha@example.com" and message "See you there"'


def test_planner_makes_one_fill_step_and_no_submit(env):
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    rt, ws = env
    r = plan_request(TemplatePlanner(), GOAL, rt.registry, rt.policy, ws)
    assert r.status == "ok", (r.message, r.issues)
    [step] = r.plan.steps
    assert step.tool_id == "browser.fill_form"
    assert step.args["fields"] == {"name": "Asha Rao", "email": "asha@example.com", "message": "See you there"}
    assert not any("submit" in s.id for s in rt.registry.specs())   # ORION has no submit tool at all


def test_values_not_in_request_are_rejected(env):
    from orion.planner.schemas import Goal, Plan, PlanStep
    from orion.planner.validator import validate_plan
    rt, ws = env
    g = Goal(request='fill the form on signup.html with name "Asha"', objective="o")
    p = Plan(goal_id=g.goal_id, steps=[PlanStep(id="f", description="f", tool_id="browser.fill_form",
                                                args={"page": "signup.html",
                                                      "fields": {"name": "Asha", "email": "made.up@x.com"}})])
    errs = [i for i in validate_plan(p, g, rt.registry, rt.policy, ws) if i.severity == "error"]
    assert any(i.code == "intent_drift" and "email" in i.message for i in errs)


@pytest.mark.real
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_fill_form_real_window_left_open_not_submitted(env):
    import os
    import signal
    from playwright.sync_api import sync_playwright
    from orion.execution.runtime import ToolCall
    from orion.orchestration.cancel import CancelToken
    rt, ws = env
    r = rt.execute(ToolCall(tool_id="browser.fill_form",
                            args={"page": "signup.html",
                                  "fields": {"Name": "Asha Rao", "Email": "asha@example.com"}}), CancelToken())
    assert r.ok, r.evidence
    pid, port = r.output["pid"], r.output["port"]
    try:
        with sync_playwright() as pw:   # reconnect: the window must still be there, filled, not submitted
            b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            page = next(p for c in b.contexts for p in c.pages if "signup" in p.url)
            assert page.locator("#name").input_value() == "Asha Rao"
            assert page.locator("#email").input_value() == "asha@example.com"
            assert page.evaluate("document.body.dataset.submitted") is None
    finally:
        os.kill(pid, signal.SIGTERM)
