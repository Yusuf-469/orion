"""Calculator: planner and input checks offline; real button pressing marked `real` (own window, closed after)."""

import sys

import pytest

from orion.tools.windows.calculator import CalcArgs, evaluate, normalize


def test_expression_rules():
    assert evaluate(normalize("1250 x 12 + 300")) == 15300
    assert evaluate(normalize("12+3*4")) == 24   # Windows 11 Calculator uses normal precedence
    for bad in ("2**10", "__import__('os')", "(1+2)*3", "-5+1", "1+", "abc"):
        with pytest.raises(ValueError):
            CalcArgs(expression=bad)


def test_planner_understands_calculate(tmp_path):
    from orion.app.main_window import build_registry
    from orion.planner.service import plan_request
    from orion.planner.template import TemplatePlanner
    from orion.policy import PolicyEngine
    from orion.tools import Permission
    reg, pol = build_registry(), PolicyEngine(frozenset(Permission))
    for goal in ("calculate 1250*12+300 in calculator", "what is 7 x 6?", "work out 10 / 4"):
        r = plan_request(TemplatePlanner(), goal, reg, pol, tmp_path)
        assert r.status == "ok" and r.plan.steps[0].tool_id == "calculator.compute", goal
    assert plan_request(TemplatePlanner(), "what is the weather", reg, pol, tmp_path).status == "unsupported"


@pytest.mark.real
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
@pytest.mark.parametrize("expr,expected", [("1250*12+300", "15300"), ("10/4", "2.5"), ("12+3*4", "24")])
def test_real_calculator(tmp_path, expr, expected):
    import uiautomation as auto
    from orion.app.main_window import build_registry
    from orion.execution.runtime import ToolCall, ToolRuntime
    from orion.orchestration.cancel import CancelToken
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.tools import Permission
    before = sum(1 for w in auto.GetRootControl().GetChildren() if w.Name == "Calculator")
    rt = ToolRuntime(build_registry(), PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), tmp_path)
    r = rt.execute(ToolCall(tool_id="calculator.compute", args={"expression": expr}), CancelToken())
    assert r.ok, r.evidence
    assert r.output["result"] == expected
    import time
    time.sleep(1)
    after = sum(1 for w in auto.GetRootControl().GetChildren() if w.Name == "Calculator")
    assert after == before   # ORION closed its own window
