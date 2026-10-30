"""Full paths reach any file on the PC: reads are free, changes outside the workspace ask first,
system folders and other users' files ask twice. Real disk I/O only under pytest's tmp dir."""

import pytest

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.policy.engine import Decision, PolicyDecision
from orion.tools import ErrorCode, Permission, ToolError, ToolRegistry
from orion.tools.files import TRASH_DIR, file_tools
from orion.tools.files.workspace import protected_reason, resolve_path
from orion.tools.write_document import ReadDocumentTool

pytestmark = pytest.mark.safety


class Answers:
    """Answers confirmations in order and records what was asked."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def confirm(self, req, token):
        self.asked.append(req)
        return self.answers.pop(0) if self.answers else False


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "workspace").mkdir()
    return tmp_path / "workspace"


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "elsewhere"
    d.mkdir()
    (d / "notes.txt").write_text("from outside")
    return d


def runtime(ws, confirmer=None):
    reg = ToolRegistry()
    for t in [*file_tools(), ReadDocumentTool()]:
        reg.register(t)
    return ToolRuntime(reg, PolicyEngine(frozenset(Permission)), confirmer or DenyAllConfirmer(), ws)


def call(rt, tool_id, **args):
    return rt.execute(ToolCall(tool_id=tool_id, args=args), CancelToken())


def test_reads_and_lists_anywhere_without_asking(ws, outside):
    conf = Answers()
    rt = runtime(ws, conf)
    r = call(rt, "files.read", path=str(outside / "notes.txt"))
    assert r.ok and r.output["text"] == "from outside" and r.output["path"] == str(outside / "notes.txt")
    assert call(rt, "docs.read_document", path=str(outside / "notes.txt")).output["text"] == "from outside"
    assert [e["name"] for e in call(rt, "files.list", path=str(outside)).output["entries"]] == ["notes.txt"]
    assert conf.asked == []


def test_missing_absolute_file_says_so_without_mentioning_the_workspace(ws, outside):
    r = call(runtime(ws), "files.read", path=str(outside / "nope.txt"))
    assert r.error_code == ErrorCode.TARGET_NOT_FOUND and "workspace" not in r.error_message


def test_write_outside_asks_once_then_writes_and_verifies(ws, outside):
    conf = Answers(True)
    target = outside / "new.txt"
    r = call(runtime(ws, conf), "files.write_new", path=str(target), content="hi")
    assert r.ok and target.read_text() == "hi"
    assert len(conf.asked) == 1 and str(target) in conf.asked[0].action


def test_write_inside_workspace_still_does_not_ask(ws):
    conf = Answers()
    assert call(runtime(ws, conf), "files.write_new", path="in.txt", content="x").ok
    assert conf.asked == []


def test_copy_into_workspace_is_free_copy_out_asks(ws, outside):
    conf = Answers(True)
    rt = runtime(ws, conf)
    assert call(rt, "files.copy", src=str(outside / "notes.txt"), dst="copied.txt").ok
    assert conf.asked == [] and (ws / "copied.txt").read_text() == "from outside"
    assert call(rt, "files.copy", src="copied.txt", dst=str(outside / "back.txt")).ok
    assert len(conf.asked) == 1 and (outside / "back.txt").read_text() == "from outside"


def test_delete_outside_asks_and_moves_to_workspace_trash(ws, outside):
    conf = Answers(True)
    r = call(runtime(ws, conf), "files.delete", path=str(outside / "notes.txt"))
    assert r.ok and not (outside / "notes.txt").exists()
    assert [p.read_text() for p in (ws / TRASH_DIR).iterdir()] == ["from outside"]


def test_protected_location_needs_a_second_yes(ws):
    conf = Answers(True, False)   # yes to the action, no to "are you sure?"
    target = r"C:\Windows\orion_should_never_exist.txt"
    r = call(runtime(ws, conf), "files.write_new", path=target, content="x")
    assert r.error_code == ErrorCode.CONFIRMATION_REQUIRED
    assert len(conf.asked) == 2 and "system folder" in conf.asked[1].consequence
    from pathlib import Path
    assert not Path(target).exists()


def test_protected_reasons(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\me")
    assert protected_reason(resolve_path(tmp_path, r"C:\Windows\System32\x.dll"))
    assert protected_reason(resolve_path(tmp_path, r"C:\Program Files\App\a.txt"))
    assert "another user" in protected_reason(resolve_path(tmp_path, r"C:\Users\someone\Desktop\a.txt"))
    assert protected_reason(resolve_path(tmp_path, r"C:\Users\me\Desktop\a.txt")) is None
    assert protected_reason(resolve_path(tmp_path, r"C:\Users\Public\a.txt")) is None
    assert protected_reason(resolve_path(tmp_path, r"D:\Projects\a.txt")) is None


@pytest.mark.parametrize("bad", [r"\\server\share\x.txt", r"C:\notes.txt:hidden", r"C:\Users\x\..\y.txt",
                                 r"C:\temp\CON", r"C:\temp\name. ", "C:relative.txt", "a\x00b"])
def test_dangerous_full_paths_rejected(ws, bad):
    with pytest.raises(ToolError) as e:
        resolve_path(ws, bad)
    assert e.value.code in (ErrorCode.PERMISSION_DENIED, ErrorCode.INVALID_INPUT)


def test_a_call_can_raise_but_never_lower_the_policy():
    pol = PolicyEngine(frozenset(Permission))
    deny = PolicyDecision(Decision.DENY, "no", "t", None)
    allow = PolicyDecision(Decision.ALLOW, "ok", "t", None)
    assert pol.escalate(deny, "outside").decision is Decision.DENY
    assert pol.escalate(allow, "outside").decision is Decision.CONFIRM
    assert pol.escalate(allow, None).decision is Decision.ALLOW
