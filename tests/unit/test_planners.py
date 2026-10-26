"""Template planner and the LLM tool-calling loop (with fake backends; mock)."""

import json

import pytest

from orion.planner.llm import LLMPlanner, extract_json
from orion.planner.service import plan_request
from orion.planner.template import TemplatePlanner
from orion.policy import PolicyEngine
from orion.tools import Permission, ToolRegistry
from orion.tools.files import file_tools
from orion.tools.windows.launch import LaunchAppTool

ALL = frozenset(Permission)


@pytest.fixture
def env(tmp_path):
    reg = ToolRegistry()
    for t in [*file_tools(), LaunchAppTool()]:
        reg.register(t)
    return reg, PolicyEngine(ALL), tmp_path


def tplan(env, request):
    reg, pol, ws = env
    return plan_request(TemplatePlanner(), request, reg, pol, ws)


# --- template planner ---------------------------------------------------------------

def test_create_file(env):
    r = tplan(env, 'create a file notes/todo.txt containing "buy milk"')
    assert r.status == "ok", r.issues
    s = r.plan.steps[0]
    assert s.tool_id == "files.write_new" and s.args == {"path": "notes/todo.txt", "content": "buy milk"}
    assert r.goal.authorized_outputs == ["notes/todo.txt"]
    assert r.goal.completion_checks[0].kind == "file_contains"


def test_multi_step_chain_with_dependencies(env):
    r = tplan(env, "create a file a.txt containing hello then copy a.txt to b.txt then open notepad")
    assert r.status == "ok", r.issues
    assert [s.tool_id for s in r.plan.steps] == ["files.write_new", "files.copy", "app.launch"]
    assert [s.depends_on for s in r.plan.steps] == [[], ["s1"], ["s2"]]


def test_move_is_copy_then_confirmed_delete(env):
    r = tplan(env, "move report.txt to archive/report.txt")
    assert r.status == "ok", r.issues
    copy, delete = r.plan.steps
    assert delete.tool_id == "files.delete" and delete.checkpoint_before and delete.depends_on == [copy.id]
    kinds = {c.kind for c in r.goal.completion_checks}
    assert kinds == {"file_exists", "file_absent"}   # the copy exists, the source is gone
    assert r.goal.constraints.allow_delete and r.goal.risk == "medium"


def test_backup_then_delete_the_original(env):
    r = tplan(env, "back up data.csv then delete the original")
    assert r.status == "ok", r.issues
    assert r.plan.steps[0].args == {"src": "data.csv", "dst": "data.csv.bak"}
    assert r.plan.steps[1].args == {"path": "data.csv"}


def test_contents_uses_reference(env):
    r = tplan(env, "put the contents of in.txt into out.txt")
    assert r.status == "ok", r.issues
    assert r.plan.steps[1].args["content"] == "${s1.text}"


@pytest.mark.parametrize("request_text,question_part", [
    ("create a file", "called"),
    ("create a file notes.txt", "contain"),
    ("copy report.txt", "Where"),
    ("delete it", "refer"),
])
def test_missing_information_asks_instead_of_guessing(env, request_text, question_part):
    r = tplan(env, request_text)
    assert r.status == "clarify" and r.plan is None
    assert question_part in r.questions[0]


@pytest.mark.parametrize("request_text", ["email my boss the report", "format the C drive", "buy a laptop"])
def test_unsupported_requests_are_not_guessed(env, request_text):
    r = tplan(env, request_text)
    assert r.status == "unsupported" and r.plan is None
    assert "does not understand" in r.message


def test_out_of_workspace_request_fails_validation(env):
    r = tplan(env, "create a file ..\\evil.txt containing x")
    assert r.status == "invalid"
    assert any(i.code == "outside_workspace" for i in r.issues)


def test_delete_without_permission_is_invalid_plan(env):
    reg, _, ws = env
    r = plan_request(TemplatePlanner(), "delete old.txt", reg,
                     PolicyEngine(frozenset({Permission.FILES_READ, Permission.FILES_WRITE})), ws)
    assert r.status == "invalid" and any(i.code == "permission_denied" for i in r.issues)


# --- LLM loop with fake backends -------------------------------------------------------

def good_output(**overrides):
    out = {
        "goal": {"objective": "make a note", "authorized_outputs": ["n.txt"],
                 "completion_checks": [{"kind": "file_exists", "path": "n.txt"}]},
        "plan": {"steps": [{"id": "w", "description": "write", "tool_id": "files.write_new",
                            "args": {"path": "n.txt", "content": "hi"},
                            "postconditions": [{"kind": "file_exists", "path": "n.txt"}]}]},
    }
    out.update(overrides)
    return out


class Scripted:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def llm(env, backend, **kw):
    reg, pol, ws = env
    return plan_request(LLMPlanner(backend, reg, pol, ws, **kw), "make a note", reg, pol, ws)


def test_llm_valid_plan_in_fenced_json(env):
    r = llm(env, Scripted("Sure!\n```json\n" + json.dumps(good_output()) + "\n```"))
    assert r.status == "ok" and r.metrics["attempts"] == 1
    assert r.goal.request == "make a note"


def test_llm_hallucinated_tool_is_repaired_once(env):
    bad = good_output()
    bad["plan"]["steps"][0]["tool_id"] = "shell.exec"
    backend = Scripted(json.dumps(bad), json.dumps(good_output()))
    r = llm(env, backend)
    assert r.status == "ok"
    assert r.metrics == {"attempts": 2, "parse_failures": 0, "schema_failures": 0,
                         "invalid_tool_calls": 1, "validation_failures": 1}
    assert "unknown_tool" in backend.prompts[1]


def test_llm_gives_up_and_plan_stays_invalid(env):
    bad = good_output()
    bad["plan"]["steps"][0]["tool_id"] = "shell.exec"
    r = llm(env, Scripted(json.dumps(bad), json.dumps(bad)))
    assert r.status == "invalid"


def test_llm_cannot_change_request_or_goal_link(env):
    out = good_output()
    out["goal"]["request"] = "delete everything"
    out["plan"]["goal_id"] = "someone-else"
    r = llm(env, Scripted(json.dumps(out)))
    assert r.status == "ok"
    assert r.goal.request == "make a note" and r.plan.goal_id == r.goal.goal_id


def test_llm_garbage_counts_parse_failures(env):
    r = llm(env, Scripted("I cannot help", "{not json"), max_repairs=1)
    assert r.status == "unsupported" and r.metrics["parse_failures"] == 2


def test_llm_unknown_fields_rejected(env):
    out = good_output()
    out["plan"]["steps"][0]["side_effect"] = "read_only"   # relabel attempt
    r = llm(env, Scripted(json.dumps(out), json.dumps(out)))
    assert r.status in ("unsupported", "invalid") and r.metrics["schema_failures"] == 2


def test_extract_json():
    assert extract_json('noise {"a": 1} tail') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")
