"""app.launch: start an allowlisted app and verify a new window appeared.

Windows 11 detail: Calculator's top-level window belongs to
ApplicationFrameHost.exe, not CalculatorApp.exe, so a window counts as the
app's if its process image OR its title matches. Notepad may open a new tab in
an existing window instead of a new window; that is reported as a
verification failure, not as success.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError


@dataclass(frozen=True)
class AllowedApp:
    exe: str                         # file name inside %SystemRoot%\System32
    images: frozenset[str]           # process images that own its window
    title_word: str                  # word expected in the window title


ALLOWLIST: dict[str, AllowedApp] = {
    "notepad": AllowedApp("notepad.exe", frozenset({"notepad.exe"}), "Notepad"),
    "calculator": AllowedApp("calc.exe", frozenset({"calculatorapp.exe", "calc.exe"}), "Calculator"),
    "paint": AllowedApp("mspaint.exe", frozenset({"mspaint.exe"}), "Paint"),
}


class LaunchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: Literal["notepad", "calculator", "paint"]


class LaunchOut(BaseModel):
    app: str
    hwnd: int
    pid: int
    title: str
    evidence: str


def _matches(app: AllowedApp, w) -> bool:
    return w.image in app.images or app.title_word.lower() in w.title.lower()


class LaunchAppTool(Tool[LaunchArgs, LaunchOut]):
    spec = ToolSpec(
        id="app.launch", version="1.0",
        description="Open an allowlisted app (notepad, calculator, paint) with no arguments.",
        input_model=LaunchArgs, output_model=LaunchOut, permissions=frozenset({Permission.APP_LAUNCH}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=15, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="a new visible top-level window owned by / titled for the app appears",
    )
    POLL_S = 0.2

    def run(self, args: LaunchArgs, ctx: ToolContext) -> LaunchOut:
        if sys.platform != "win32":
            raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, "app.launch is Windows-only")
        from orion.tools.windows.win32 import visible_windows

        app = ALLOWLIST[args.app]
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", app.exe)
        if not os.path.isfile(exe):
            raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, f"{exe} not found")
        before = {w.hwnd for w in visible_windows()}
        if ctx.token.is_cancelled:
            raise ToolError(ErrorCode.CANCELLED, "cancelled before launch")
        try:
            subprocess.Popen([exe], shell=False, close_fds=True)
        except OSError as e:
            raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, f"could not start {app.exe}: {e}") from None

        while time.monotonic() < ctx.deadline - self.POLL_S:
            new = [w for w in visible_windows() if w.hwnd not in before and _matches(app, w)]
            if new:
                w = new[0]
                return LaunchOut(app=args.app, hwnd=w.hwnd, pid=w.pid, title=w.title,
                                 evidence=f"new window '{w.title}' (hwnd {w.hwnd}, {w.image or 'image n/a'}) appeared")
            if ctx.token.wait(self.POLL_S):
                raise ToolError(ErrorCode.CANCELLED, f"cancelled after starting {app.exe}; window not yet seen",
                                note="the app may still open")
        raise ToolError(ErrorCode.VERIFICATION_FAILED,
                        f"started {app.exe} but no new {app.title_word} window appeared "
                        f"(it may have reused an existing window, e.g. a Notepad tab)")
