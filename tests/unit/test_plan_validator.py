"""Plan validator: invalid or hallucinated plans must be rejected (Stage 3 gate)."""

import pytest

from orion.planner.schemas import Constraints, FileContains, FileExists, Goal, Plan, PlanStep
from orion.planner.validator import topo_order, validate_plan
from orion.policy import PolicyEngine
from orion.tools import Permission, ToolRegistry
from orion.tools.files import file_tools
from orion.tools.windows.launch import LaunchAppTool

ALL = frozenset(Permission)


@pytest.fixture
def ctx(tmp_path):
    reg = ToolRegistry()
    for t in [*file_tools(), LaunchAppTool()]:
        reg.register(t)
    return reg, tmp_path


def goal(**kw):
    # The request names every path these tests write, so intent-drift checks stay quiet unless tested.
    base = dict(goal_id="g1", objective="o", authorized_outputs=["out"],
                request="out/a.txt out/b.txt elsewhere/a.txt outside/a.txt ..\\a.txt containing hi x 1",
                completion_checks=[FileExists(path="out/a.txt")])
    base.update(kw)
    return Goal(**base)


def step(id, tool, args, deps=(), **kw):
    return PlanStep(id=id, description=id, tool_id=tool, args=args, depends_on=list(deps), **kw)


def errors(plan, g, reg, ws, granted=ALL):
    issues = validate_plan(plan, g, reg, PolicyEngine(granted), ws)
    return {(i.code, i.step_id) for i in issues if i.severity == "error"}, issues


def test_valid_two_step_plan(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[
        step("write", "files.write_new", {"path": "out/a.txt", "content": "hi"},
             postconditions=[FileContains(path="out/a.txt", text="hi")]),
        step("copy", "files.copy", {"src": "out/a.txt", "dst": "out/b.txt"}, ["write"],
             postconditions=[FileExists(path="out/b.txt")]),
    ])
    errs, _ = errors(plan, goal(), reg, ws)
    assert errs == set()


def test_invented_tool_rejected(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[step("x", "shell.run", {"cmd": "rm -rf /"})])
    assert ("unknown_tool", "x") in errors(plan, goal(), reg, ws)[0]


def test_bad_args_rejected(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "out/a.txt"})])
    assert ("invalid_args", "w") in errors(plan, goal(), reg, ws)[0]


def test_missing_and_cyclic_dependencies(ctx):
    reg, ws = ctx
    p1 = Plan(goal_id="g1", steps=[step("a", "files.list", {}, ["ghost"])])
    assert ("unknown_dependency", "a") in errors(p1, goal(), reg, ws)[0]
    p2 = Plan(goal_id="g1", steps=[step("a", "files.list", {}, ["b"]), step("b", "files.list", {}, ["a"])])
    assert ("cycle", None) in errors(p2, goal(), reg, ws)[0]
    p3 = Plan(goal_id="g1", steps=[step("a", "files.list", {}, ["a"])])
    assert ("self_dependency", "a") in errors(p3, goal(), reg, ws)[0]


def test_duplicate_ids_rejected(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[step("a", "files.list", {}), step("a", "files.list", {})])
    assert ("duplicate_step", "a") in errors(plan, goal(), reg, ws)[0]


def test_reference_must_be_ancestor_and_real_field(ctx):
    reg, ws = ctx
    ok = Plan(goal_id="g1", steps=[
        step("r", "files.read", {"path": "src.txt"}),
        step("w", "files.write_new", {"path": "out/a.txt", "content": "${r.text}"}, ["r"]),
    ])
    assert errors(ok, goal(), reg, ws)[0] == set()
    not_dep = Plan(goal_id="g1", steps=[
        step("r", "files.read", {"path": "src.txt"}),
        step("w", "files.write_new", {"path": "out/a.txt", "content": "${r.text}"}),
    ])
    assert ("bad_reference", "w") in errors(not_dep, goal(), reg, ws)[0]
    bad_field = Plan(goal_id="g1", steps=[
        step("r", "files.read", {"path": "src.txt"}),
        step("w", "files.write_new", {"path": "out/a.txt", "content": "${r.password}"}, ["r"]),
    ])
    assert ("bad_reference", "w") in errors(bad_field, goal(), reg, ws)[0]


def test_write_target_must_be_literal(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[
        step("r", "files.read", {"path": "src.txt"}),
        step("w", "files.write_new", {"path": "${r.text}", "content": "x"}, ["r"]),
    ])
    assert ("unchecked_write_target", "w") in errors(plan, goal(), reg, ws)[0]


def test_writes_must_be_authorized_and_inside_workspace(ctx):
    reg, ws = ctx
    p1 = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "elsewhere/a.txt", "content": "x"})])
    assert ("unauthorized_output", "w") in errors(p1, goal(), reg, ws)[0]
    p2 = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "..\\a.txt", "content": "x"})])
    assert ("outside_workspace", "w") in errors(p2, goal(), reg, ws)[0]
    # "out" must not authorize a sibling such as "outside/"
    p3 = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "outside/a.txt", "content": "x"})])
    assert ("unauthorized_output", "w") in errors(p3, goal(), reg, ws)[0]


def test_denied_permission_reported(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[step("d", "files.delete", {"path": "out/a.txt"}, checkpoint_before=True)])
    g = goal(constraints=Constraints(preserve_source_files=False, allow_delete=True))
    errs, _ = errors(plan, g, reg, ws, granted=frozenset({Permission.FILES_READ}))
    assert ("permission_denied", "d") in errs


def test_contradiction_with_constraints(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[step("d", "files.delete", {"path": "out/a.txt"}, checkpoint_before=True)])
    assert ("contradiction", "d") in errors(plan, goal(), reg, ws)[0]
    launch = Plan(goal_id="g1", steps=[step("l", "app.launch", {"app": "notepad"})])
    g = goal(constraints=Constraints(allow_app_launch=False))
    assert ("contradiction", "l") in errors(launch, g, reg, ws)[0]


def test_consequential_needs_checkpoint(ctx):
    reg, ws = ctx
    g = goal(constraints=Constraints(preserve_source_files=False, allow_delete=True))
    plan = Plan(goal_id="g1", steps=[step("d", "files.delete", {"path": "out/a.txt"})])
    assert ("missing_checkpoint", "d") in errors(plan, g, reg, ws)[0]


def test_irreversible_first_is_warning(ctx):
    reg, ws = ctx
    g = goal(constraints=Constraints(preserve_source_files=False, allow_delete=True))
    plan = Plan(goal_id="g1", steps=[
        step("d", "files.delete", {"path": "out/a.txt"}, checkpoint_before=True),
        step("w", "files.write_new", {"path": "out/b.txt", "content": "x"}, ["d"]),
    ])
    errs, issues = errors(plan, g, reg, ws)
    assert errs == set()
    assert any(i.code == "irreversible_first" for i in issues)


def test_missing_info_blocks_plan(ctx):
    reg, ws = ctx
    plan = Plan(goal_id="g1", steps=[step("l", "files.list", {})])
    errs, _ = errors(plan, goal(missing_info=["Which file?"]), reg, ws)
    assert ("missing_info", None) in errs


def test_intent_drift_invented_destination(ctx):
    """Observed with Phi-3.5 (p15): 'copy report.txt' got an invented destination."""
    reg, ws = ctx
    g = goal(request="copy report.txt", authorized_outputs=["copied_report.txt"])
    plan = Plan(goal_id="g1", steps=[step("c", "files.copy", {"src": "report.txt", "dst": "copied_report.txt"})])
    assert ("intent_drift", "c") in errors(plan, g, reg, ws)[0]


def test_intent_drift_silently_rewritten_path(ctx):
    """Observed with Phi-3.5 (p21): '..\\escape.txt' was rewritten to 'escape.txt'."""
    reg, ws = ctx
    g = goal(request="create a file ..\\escape.txt containing x", authorized_outputs=["escape.txt"])
    plan = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "escape.txt", "content": "x"})])
    errs, issues = errors(plan, g, reg, ws)
    assert ("intent_drift", "w") in errs
    assert any(i.code == "intent_drift" and i.severity == "warning" for i in issues)


def test_intent_drift_invented_content(ctx):
    """Observed with Phi-3.5 (p14): no content given, model invented 'Initial content for notes.txt'."""
    reg, ws = ctx
    g = goal(request="create a file notes.txt", authorized_outputs=["notes.txt"])
    plan = Plan(goal_id="g1", steps=[step("w", "files.write_new",
                                          {"path": "notes.txt", "content": "Initial content for notes.txt"})])
    assert ("intent_drift", "w") in errors(plan, g, reg, ws)[0]
    g2 = goal(request="create a file notes.txt containing   Buy  Milk", authorized_outputs=["notes.txt"])
    ok = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "notes.txt", "content": "buy milk"})])
    assert errors(ok, g2, reg, ws)[0] == set()


def test_empty_content_needs_explicit_request(ctx):
    """Observed with Phi-3.5 (dev d11): content '' slipped past the substring check."""
    reg, ws = ctx
    g = goal(request="write something nice into poem.txt", authorized_outputs=["poem.txt"])
    plan = Plan(goal_id="g1", steps=[step("w", "files.write_new", {"path": "poem.txt", "content": ""})])
    assert ("intent_drift", "w") in errors(plan, g, reg, ws)[0]
    g2 = goal(request="create an empty file poem.txt", authorized_outputs=["poem.txt"])
    assert errors(plan, g2, reg, ws)[0] == set()


def test_intent_named_paths_and_bak_backups_pass(ctx):
    reg, ws = ctx
    g = goal(request='back up "my data.csv" then copy a.txt to out/b.txt',
             authorized_outputs=["my data.csv.bak", "out/b.txt"])
    plan = Plan(goal_id="g1", steps=[
        step("b", "files.copy", {"src": "my data.csv", "dst": "my data.csv.bak"}),
        step("c", "files.copy", {"src": "a.txt", "dst": "out/b.txt"}, ["b"]),
    ])
    errs, issues = errors(plan, g, reg, ws)
    assert errs == set() and not any(i.code == "intent_drift" for i in issues)


def test_topo_order_follows_dependencies():
    plan = Plan(goal_id="g", steps=[
        PlanStep(id="c", description="", tool_id="files.list", depends_on=["b"]),
        PlanStep(id="a", description="", tool_id="files.list"),
        PlanStep(id="b", description="", tool_id="files.list", depends_on=["a"]),
    ])
    assert topo_order(plan) == ["a", "b", "c"]


@pytest.mark.parametrize("request_text,warned", [
    ("fill the form and submit it out/a.txt", True),
    ("write out/a.txt then send it to bob", True),
    ("buy the item out/a.txt", True),
    ('fill the form with email "a@b.c" out/a.txt', False),
    ("out/a.txt containing hi", False),
])
def test_parts_orion_never_does_are_announced_not_dropped(ctx, request_text, warned):
    reg, ws = ctx
    g = goal(request=request_text)
    p = Plan(goal_id="g1", steps=[step("s1", "files.write_new", {"path": "out/a.txt", "content": "hi"},
                                       postconditions=[FileExists(path="out/a.txt")])])
    _, issues = errors(p, g, reg, ws)
    assert any(i.code == "will_not_do" and i.severity == "warning" for i in issues) is warned
