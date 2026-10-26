"""Real Notepad control (marked `real`). Uses a temp workspace; never reads the user's restored tabs.

If no Notepad window existed before the test, the test closes the window it caused at the end
(Notepad keeps the user's session); otherwise it closes only its own tab.
"""

import sys
from pathlib import Path

import pytest

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
    f = ws / "orion_np_test.txt"
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


def test_guard_refuses_files_not_open(env):
    rt, ws = env
    (ws / "never_opened.txt").write_text("x")
    r = call(rt, "notepad.read_text", path="never_opened.txt")
    assert not r.ok and "will not read other tabs" in r.evidence
    r = call(rt, "notepad.set_text", path="never_opened.txt", text="y")
    assert not r.ok and (ws / "never_opened.txt").read_text() == "x"
