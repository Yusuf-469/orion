"""Real Notepad control (marked `real`). Uses a temp workspace; never reads the user's restored tabs.

If no Notepad window existed before the test, the test closes the window it caused at the end
(Notepad keeps the user's session); otherwise it closes only its own tab.
"""

import sys
from pathlib import Path

import pytest

import uuid

P = f"orion-test-{uuid.uuid4().hex[:6]}"   # unique: never collides with the user's tabs or old runs

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]


@pytest.fixture
def env(tmp_path):
    import uiautomation as auto
    from orion.execution.runtime import ToolRuntime
    from orion.policy import DenyAllConfirmer, PolicyEngine
    from orion.tools import Permission, ToolRegistry
    from orion.tools.windows.notepad import notepad_tools

    had_window = any(w.ClassName == "Notepad" for w in auto.GetRootControl().GetChildren())
    ws = tmp_path / "ws"
    ws.mkdir()
    reg = ToolRegistry()
    for t in notepad_tools():
        reg.register(t)
    rt = ToolRuntime(reg, PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), ws)
    yield rt, ws
    from orion.execution.runtime import ToolCall
    from orion.orchestration.cancel import CancelToken
    for f in ws.glob("*.txt"):
        rt.execute(ToolCall(tool_id="notepad.close_tab", args={"path": f.name}), CancelToken())
    if not had_window:
        for w in auto.GetRootControl().GetChildren():
            if w.ClassName == "Notepad":
                w.GetWindowPattern().Close()


def call(rt, tool, **args):
    from orion.execution.runtime import ToolCall
    from orion.orchestration.cancel import CancelToken
    return rt.execute(ToolCall(tool_id=tool, args=args), CancelToken())


def test_open_read_set_save_close(env):
    rt, ws = env
    f = ws / f"{P}-np.txt"
    f.write_text("first line", encoding="utf-8")
    r = call(rt, "notepad.open_file", path=f.name)
    assert r.ok, r.evidence
    r = call(rt, "notepad.read_text", path=f.name)
    assert r.ok and r.output["text"] == "first line"
    r = call(rt, "notepad.set_text", path=f.name, text="written by ORION\nsecond line")
    assert r.ok, r.evidence
    assert f.read_text(encoding="utf-8-sig").replace("\r\n", "\n") == "written by ORION\nsecond line"
    backups = list((ws / ".orion_backups").iterdir())
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "first line"
    r = call(rt, "notepad.close_tab", path=f.name)
    assert r.ok, r.evidence
    assert not call(rt, "notepad.read_text", path=f.name).ok   # tab gone: guard refuses


def test_tab_matching_is_exact():
    from orion.tools.windows.notepad import _tab_is
    assert _tab_is("note.txt. Unmodified.", "note.txt")
    assert _tab_is("Note.TXT. Modified.", "note.txt")
    assert not _tab_is("my note.txt. Unmodified.", "note.txt")
    assert not _tab_is("note.txt.bak. Unmodified.", "note.txt")


def test_reopening_selects_existing_tab_no_duplicate(env):
    import uiautomation as auto
    from orion.tools.windows.notepad import find_tabs
    rt, ws = env
    (ws / f"{P}-dup.txt").write_text("x", encoding="utf-8")
    assert call(rt, "notepad.open_file", path=f"{P}-dup.txt").ok
    r = call(rt, "notepad.open_file", path=f"{P}-dup.txt")
    assert r.ok and "selected its existing tab" in r.evidence
    with auto.UIAutomationInitializerInThread():
        assert len(find_tabs(auto, f"{P}-dup.txt")) == 1


def test_guard_refuses_files_not_open(env):
    rt, ws = env
    (ws / f"{P}-never.txt").write_text("x")
    r = call(rt, "notepad.read_text", path=f"{P}-never.txt")
    assert not r.ok and "will not read other tabs" in r.evidence
    r = call(rt, "notepad.set_text", path=f"{P}-never.txt", text="y")
    assert not r.ok and (ws / f"{P}-never.txt").read_text() == "x"
