"""desktop.look/click on ORION's canvas demo, whose buttons UI Automation cannot see.
Marked `real`: opens a window on the desktop and clicks inside it (only ORION's own demo window)."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import Permission, ToolRegistry
from orion.tools.desktop import desktop_tools

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
APP = Path(__file__).resolve().parents[2] / "demo" / "apps" / "canvas_buttons.py"


@pytest.fixture
def canvas(tmp_path):
    log = tmp_path / "clicks.log"
    p = subprocess.Popen([sys.executable, str(APP), str(log), "+-1700+200"])   # second monitor, away from the user
    time.sleep(2.5)
    yield log
    p.terminate()


def call(rt, tool, **args):
    return rt.execute(ToolCall(tool_id=tool, args=args), CancelToken())


def test_sees_and_clicks_a_drawn_button(canvas, tmp_path):
    reg = ToolRegistry()
    for t in desktop_tools():
        reg.register(t)
    rt = ToolRuntime(reg, PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), tmp_path)
    look = call(rt, "desktop.look", app="canvas demo")
    assert look.ok, look.error_message
    seen = {e["name"]: e for e in look.output["elements"] if e.get("seen") == "on screen"}
    assert "Export" in seen, sorted(seen)
    assert seen["Close Report"].get("consequential") is None   # "close" is not a sending word
    r = call(rt, "desktop.click", ref=seen["Export"]["ref"])
    assert r.ok, r.error_message
    time.sleep(0.5)
    assert "Export" in canvas.read_text()
