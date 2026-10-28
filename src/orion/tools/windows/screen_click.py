"""Visual grounding tools: find a control by what is visible and click it.

screen.click works only in allowlisted windows (CLICKABLE_WINDOWS). It merges UI Automation
elements (excluding the window frame's own Minimize/Maximize/Close) with local OCR of the window,
abstains when unsure or ambiguous, prefers UIA Invoke when the control supports it, and otherwise
clicks with the mouse only after checking that the target window is what is under that point.
The cursor is put back afterwards. Screenshots are kept in memory only.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.files.workspace import rel_display, resolve_in_workspace

CANVAS_TITLE = "ORION Canvas Demo"
CLICKABLE_WINDOWS = (CANVAS_TITLE,)   # adding an app here needs a safety review
CANVAS_APP = Path(__file__).resolve().parents[4] / "demo" / "apps" / "canvas_buttons.py"
_FRAME_IDS = {"Minimize", "Maximize", "Restore", "Close"}


def _find_window(auto, title: str):
    wins = [w for w in auto.GetRootControl().GetChildren() if w.Name == title]
    if len(wins) != 1:
        raise ToolError(ErrorCode.TARGET_NOT_FOUND if not wins else ErrorCode.STALE_STATE,
                        f"expected one '{title}' window, found {len(wins)}")
    return wins[0]


def _uia_candidates(auto, win):
    from orion.grounding.locate import Candidate
    from orion.grounding.screen import Box
    out = []
    for c, _ in auto.WalkControl(win, maxDepth=12):
        if not c.Name or c.ControlTypeName in ("WindowControl", "TitleBarControl", "PaneControl"):
            continue
        if c.AutomationId in _FRAME_IDS or c.GetParentControl().ControlTypeName == "TitleBarControl":
            continue   # never the window frame's own buttons ("Close" would close the app)
        r = c.BoundingRectangle
        if r.width() <= 0 or r.height() <= 0:
            continue
        out.append(Candidate(c.Name, Box(r.left, r.top, r.right, r.bottom), "uia", c.ControlTypeName, 1.0,
                             bool(c.GetPattern(auto.PatternId.InvokePattern))))
    return out


def _root_window_at(x: int, y: int) -> int:
    user32 = ctypes.WinDLL("user32")
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.restype = wintypes.HWND
    h = user32.WindowFromPoint(wintypes.POINT(x, y))
    return int(user32.GetAncestor(h, 2) or 0) if h else 0   # GA_ROOT


class ClickArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: Literal["ORION Canvas Demo"]
    target: str = Field(min_length=1, max_length=100)


class ClickOut(BaseModel):
    window: str
    clicked: str
    source: str
    score: float
    evidence: str


class ScreenClickTool(Tool[ClickArgs, ClickOut]):
    spec = ToolSpec(
        id="screen.click", version="1.0",
        description="Click a control by its visible label in an allowlisted window (UIA + OCR, abstains if unsure).",
        input_model=ClickArgs, output_model=ClickOut, permissions=frozenset({Permission.APP_CONTROL}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=40, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the app's own reaction is checked by the step's postconditions",
    )

    def run(self, args: ClickArgs, ctx: ToolContext) -> ClickOut:
        if sys.platform != "win32":
            raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, "screen.click is Windows-only")
        from orion.grounding.locate import locate, merge
        from orion.grounding.screen import ensure_dpi_aware, ocr_window
        from orion.tools.windows.notepad import _uia
        ensure_dpi_aware()
        with _uia() as auto:
            win = _find_window(auto, args.window)
            win.SetActive()
            time.sleep(0.3)
            hwnd = win.NativeWindowHandle
            cands = merge(_uia_candidates(auto, win), ocr_window(hwnd))
            found = locate(args.target, cands)
            if found.candidate is None:
                raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"did not click: {found.reason}")
            c = found.candidate
            if ctx.token.is_cancelled:
                raise ToolError(ErrorCode.CANCELLED, "cancelled before clicking")
            if c.invokable and c.source != "ocr":
                ctrl = next(x for x, _ in auto.WalkControl(win, maxDepth=12) if x.Name == c.text)
                ctrl.GetInvokePattern().Invoke()
                how = "UIA Invoke"
            else:
                x, y = c.box.center
                if _root_window_at(x, y) != hwnd:
                    raise ToolError(ErrorCode.STALE_STATE,
                                    f"another window covers '{c.text}' at ({x},{y}); did not click")
                old = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(old))
                auto.Click(x, y, waitTime=0.1)
                ctypes.windll.user32.SetCursorPos(old.x, old.y)
                how = f"mouse at ({x},{y})"
            time.sleep(0.5)   # let the app react before postconditions are checked
        return ClickOut(window=args.window, clicked=c.text, source=c.source, score=round(found.score, 3),
                        evidence=f"clicked '{c.text}' found via {c.source} (score {found.score:.2f}) using {how}")


class OpenCanvasArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log: str = Field(default="canvas_clicks.log", pattern=r"(?i)\.log$")


class OpenCanvasOut(BaseModel):
    log: str
    evidence: str


class OpenCanvasDemoTool(Tool[OpenCanvasArgs, OpenCanvasOut]):
    spec = ToolSpec(
        id="demo.open_canvas_app", version="1.0",
        description="Open ORION's canvas demo app (buttons drawn on screen, invisible to UI Automation).",
        input_model=OpenCanvasArgs, output_model=OpenCanvasOut,
        permissions=frozenset({Permission.APP_LAUNCH}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=20, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the demo window appears",
    )

    def run(self, args: OpenCanvasArgs, ctx: ToolContext) -> OpenCanvasOut:
        from orion.tools.windows.notepad import _uia
        log = resolve_in_workspace(ctx.workspace, args.log)
        with _uia() as auto:
            if any(w.Name == CANVAS_TITLE for w in auto.GetRootControl().GetChildren()):
                return OpenCanvasOut(log=rel_display(ctx.workspace, log), evidence="the demo app is already open")
            exe = Path(sys.executable).with_name("pythonw.exe")
            subprocess.Popen([str(exe if exe.exists() else sys.executable), str(CANVAS_APP), str(log)],
                             close_fds=True)
            while time.monotonic() < ctx.deadline - 0.5:
                if any(w.Name == CANVAS_TITLE for w in auto.GetRootControl().GetChildren()):
                    return OpenCanvasOut(log=rel_display(ctx.workspace, log),
                                         evidence=f"'{CANVAS_TITLE}' window is open; clicks are logged to {log.name}")
                if ctx.token.wait(0.2):
                    raise ToolError(ErrorCode.CANCELLED, "cancelled while the demo app was starting")
        raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, "the demo app window did not appear")


def screen_tools() -> list[Tool]:
    return [ScreenClickTool(), OpenCanvasDemoTool()]
