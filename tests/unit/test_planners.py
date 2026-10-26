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


def test_then_inside_unquoted_text_refuses_whole_request(env):
    """Unquoted 'then' still splits; the leftover clause is refused, so nothing wrong runs."""
    r = tplan(env, 'create a file a.txt containing first this then that')
    assert r.status == "unsupported" and r.plan is None


def test_then_inside_quotes_is_kept(env):
    r = tplan(env, 'create a file a.txt containing "first this then that" then copy a.txt to b.txt')
    assert r.status == "ok", (r.message, r.issues)
    assert r.plan.steps[0].args["content"] == "first this then that"
    assert [s.tool_id for s in r.plan.steps] == ["files.write_new", "files.copy"]


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


REQUEST = "make a note n.txt containing hi"


def llm(env, backend, request=REQUEST, **kw):
    reg, pol, ws = env
    return plan_request(LLMPlanner(backend, reg, pol, ws, **kw), request, reg, pol, ws)


def test_llm_invented_path_is_caught_as_intent_drift(env):
    """The request never names n.txt, so a plan writing it is drift (seen with Phi-3.5, p15)."""
    r = llm(env, Scripted(json.dumps(good_output()), json.dumps(good_output())), request="make a note")
    assert r.status == "invalid" and any(i.code == "intent_drift" for i in r.issues)


def test_llm_valid_plan_in_fenced_json(env):
    r = llm(env, Scripted("Sure!\n```json\n" + json.dumps(good_output()) + "\n```"))
    assert r.status == "ok" and r.metrics["attempts"] == 1
    assert r.goal.request == REQUEST


def test_llm_hallucinated_tool_is_repaired_once(env):
    bad = good_output()
    bad["plan"]["steps"][0]["tool_id"] = "shell.exec"
    backend = Scripted(json.dumps(bad), json.dumps(good_output()))
    r = llm(env, backend)
    assert r.status == "ok"
    assert r.metrics == {"attempts": 2, "parse_failures": 0, "schema_failures": 0,
                         "invalid_tool_calls": 1, "validation_failures": 1, "backend_errors": 0}
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
    assert r.goal.request == REQUEST and r.plan.goal_id == r.goal.goal_id


def test_llm_garbage_counts_parse_failures(env):
    r = llm(env, Scripted("I cannot help", "{not json"), max_repairs=1)
    assert r.status == "unsupported" and r.metrics["parse_failures"] == 2


def test_llm_wrong_shape_is_schema_failure_not_parse_failure(env):
    shaped_wrong = json.dumps({"goal": {"objective": "x"}, "plan": [{"id": "a"}]})
    r = llm(env, Scripted(shaped_wrong, shaped_wrong))
    assert r.metrics["parse_failures"] == 0 and r.metrics["schema_failures"] == 2


def test_llm_unknown_fields_rejected(env):
    out = good_output()
    out["plan"]["steps"][0]["side_effect"] = "read_only"   # relabel attempt
    r = llm(env, Scripted(json.dumps(out), json.dumps(out)))
    assert r.status in ("unsupported", "invalid") and r.metrics["schema_failures"] == 2


def test_llm_backend_error_is_a_failed_attempt_not_a_crash(env):
    from orion.models.ollama import LLMBackendError

    def aborting(prompt):
        raise LLMBackendError('HTTP 500: {"error":"prediction aborted, token repeat limit reached"}')

    r = llm(env, aborting)
    assert r.status == "unsupported" and r.metrics["backend_errors"] == 2 and r.plan is None


def test_ollama_backend_refuses_remote_hosts():
    from orion.models.ollama import OllamaBackend
    for url in ("http://example.com:11434", "http://10.0.0.5:11434", "https://api.example.org"):
        with pytest.raises(ValueError):
            OllamaBackend(url=url)
    OllamaBackend(url="http://localhost:11434")


def test_llm_can_decline(env):
    r = llm(env, Scripted(json.dumps({"unsupported_reason": "no tool can send email", "goal": {"objective": "x"},
                                      "plan": {"steps": []}})))
    assert r.status == "unsupported" and "no tool can send email" in r.message


def test_llm_empty_plan_without_question_is_unsupported(env):
    r = llm(env, Scripted(json.dumps({"goal": {"objective": "x"}, "plan": {"steps": []}})))
    assert r.status == "unsupported" and r.plan is None


def test_normalize_sets_safety_fields_not_the_model(env):
    out = {"goal": {"objective": "remove n.txt", "authorized_outputs": ["everything"],
                    "constraints": {"preserve_source_files": True, "allow_delete": False}},
           "plan": {"steps": [{"id": "d", "description": "delete", "tool_id": "files.delete",
                               "args": {"path": "n.txt"}, "checkpoint_before": False}]}}
    r = llm(env, Scripted(json.dumps(out)), request="remove n.txt")
    assert r.status == "ok", r.issues
    assert r.goal.authorized_outputs == ["n.txt"]          # not the model's "everything"
    assert r.plan.steps[0].checkpoint_before is True        # forced for consequential steps
    assert r.goal.constraints.allow_delete and not r.goal.constraints.preserve_source_files


def test_prompt_examples_do_not_leak_eval_prompts():
    from pathlib import Path
    from orion.planner.llm import _EXAMPLES
    texts = []
    for f in ("prompts_v1.json", "prompts_dev_v1.json"):
        texts += [p["text"] for p in json.loads((Path("research/planner_eval") / f).read_text(
            encoding="utf-8"))["prompts"]]
    for q, a in _EXAMPLES:
        assert q not in texts
        for name in ("ideas.txt", "plan.docx", "pizza"):
            assert not any(name in t for t in texts)


def test_output_schema_requires_check_kind():
    """Regression: constrained decoding let the model omit 'kind', which then failed to parse."""
    from orion.planner.llm import output_schema
    defs = output_schema()["$defs"]
    for name in ("FileExists", "FileAbsent", "FileContains", "FilesIdentical", "AppWindowOpen"):
        assert "kind" in defs[name]["required"], name


def test_extract_json():
    assert extract_json('noise {"a": 1} tail') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")
