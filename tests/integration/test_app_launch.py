"""app.launch. The `real` test opens Calculator on the desktop and closes only the window it opened."""

import sys
from pathlib import Path

import pytest

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import ErrorCode, Permission, ToolRegistry
from orion.tools.windows.launch import LaunchAppTool


def _rt(granted):
    reg = ToolRegistry()
    reg.register(LaunchAppTool())
    return ToolRuntime(reg, PolicyEngine(frozenset(granted)), DenyAllConfirmer(), Path("."))


@pytest.mark.safety
@pytest.mark.parametrize("app", ["cmd", "powershell", "C:\\Windows\\System32\\cmd.exe", "notepad.exe /p x", ""])
def test_non_allowlisted_apps_rejected(app):
    r = _rt(Permission).execute(ToolCall(tool_id="app.launch", args={"app": app}), CancelToken())
    assert r.error_code == ErrorCode.INVALID_INPUT


@pytest.mark.safety
def test_launch_needs_permission():
    r = _rt({Permission.FILES_READ}).execute(ToolCall(tool_id="app.launch", args={"app": "calculator"}),
                                              CancelToken())
    assert r.error_code == ErrorCode.PERMISSION_DENIED


@pytest.mark.real
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_real_calculator_launch_verified_and_closed():
    from orion.tools.windows.launch import ALLOWLIST, _matches
    from orion.tools.windows.win32 import post_close, visible_windows

    if any(_matches(ALLOWLIST["calculator"], w) for w in visible_windows()):
        pytest.skip("a Calculator window is already open; not touching the user's windows")
    r = _rt(Permission).execute(ToolCall(tool_id="app.launch", args={"app": "calculator"}), CancelToken())
    try:
        assert r.ok, r.evidence
        print(f"\n[real] {r.evidence} in {r.duration_s:.2f}s")
    finally:
        if r.ok:
            post_close(r.output["hwnd"])
