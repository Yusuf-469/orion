"""'Did you mean A or B?': recovery asks the user when screen.click finds several matches (mock: no screen)."""

from orion.execution.runtime import ToolResult
from orion.orchestration.cancel import KillSwitch
from orion.policy import DenyAllConfirmer
from orion.recovery import RecoveryEngine
from orion.tools.errors import ErrorCode

ARGS = {"window": "ORION Canvas Demo", "target": "Export"}
CHOICES = [{"text": "Export", "at": [260, 58], "where": "top middle"},
           {"text": "Export", "at": [260, 148], "where": "centre"}]


def ambiguous(choices=CHOICES):
    return ToolResult("screen.click", False, {"details": {"choices": choices}}, ErrorCode.TARGET_NOT_FOUND,
                      "did not click: 2 elements look like 'Export'")


class Picker:
    def __init__(self, pick):
        self.pick, self.asked = pick, None

    def confirm(self, req, token):
        return False

    def choose(self, req, options, token):
        self.asked = options
        return self.pick


def test_proposes_asking_only_for_click_ambiguity():
    eng = RecoveryEngine(None, DenyAllConfirmer())
    assert eng.propose("screen.click", ARGS, ambiguous()).kind == "ask_choice"
    assert eng.propose("screen.click", ARGS, ambiguous(CHOICES[:1])) is None          # one place: nothing to ask
    assert eng.propose("screen.click", {**ARGS, "user_choice": [1, 1]}, ambiguous()) is None   # asked already
    assert eng.propose("notepad.read_text", ARGS, ambiguous()) is None


def test_users_pick_becomes_the_retry_args():
    p = Picker(1)
    eng = RecoveryEngine(None, p)
    rec = eng.propose("screen.click", ARGS, ambiguous())
    ok, how = eng.apply(rec, KillSwitch().new_token())
    assert ok and "centre" in how
    assert p.asked == ["'Export' at the top middle", "'Export' at the centre"]
    assert rec.retry_args == {**ARGS, "user_choice": [260, 148]}


def test_no_pick_means_no_click():
    for confirmer in (Picker(None), DenyAllConfirmer()):
        eng = RecoveryEngine(None, confirmer)
        rec = eng.propose("screen.click", ARGS, ambiguous())
        ok, how = eng.apply(rec, KillSwitch().new_token())
        assert not ok and "not clicking" in how and rec.retry_args is None


def test_cancelled_token_never_asks():
    p = Picker(0)
    eng = RecoveryEngine(None, p)
    rec = eng.propose("screen.click", ARGS, ambiguous())
    tok = KillSwitch().new_token()
    tok.cancel("test")
    ok, _ = eng.apply(rec, tok)
    assert not ok and p.asked is None


def test_plans_cannot_set_the_users_choice(tmp_path):
    from orion.app.main_window import build_registry
    from orion.config import OrionConfig
    from orion.planner.schemas import Goal, Plan, PlanStep
    from orion.planner.validator import validate_plan
    from orion.policy import PolicyEngine
    req = "click Export in the canvas demo"
    goal = Goal(request=req, objective=req)
    plan = Plan(goal_id=goal.goal_id, steps=[PlanStep(id="s1", description="click", tool_id="screen.click",
                                                      args={**ARGS, "user_choice": [260, 148]})])
    issues = validate_plan(plan, goal, build_registry(),
                           PolicyEngine(frozenset(OrionConfig().granted_permissions)), tmp_path)
    assert any(i.code == "user_only_argument" for i in issues)
