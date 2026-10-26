"""Notepad tools via Windows UI Automation (Windows 11 Notepad).

Privacy guard: Windows 11 Notepad restores the user's previous tabs. ORION only
reads or writes the document when the window's ACTIVE tab is the workspace file
ORION opened (window title "<name> - Notepad", optionally with a leading "*"),
and closes only that tab. Text is set through UIA ValuePattern, not keystrokes,
so nothing can be typed into another app if focus changes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.files.workspace import rel_display, resolve_in_workspace

BACKUP_DIR = ".orion_backups"
NOTEPAD = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")


def _norm_text(t: str) -> str:
    return t.replace("\r\n", "\n").replace("\r", "\n")


class _uia:
    """Per-thread UIA (COM) initialisation; tools run on fresh threads."""

    def __enter__(self):
        import uiautomation as auto
        self._init = auto.UIAutomationInitializerInThread(debug=False)
        return auto

    def __exit__(self, *exc):
        self._init.Uninitialize()
        return False


def _title_matches(title: str, name: str) -> bool:
    return title.lstrip("*").lower().startswith(f"{name.lower()} - notepad")


def find_our_window(auto, name: str):
    """The Notepad window whose ACTIVE tab is `name`, else None. Never inspects other text."""
    for w in auto.GetRootControl().GetChildren():
        if w.ClassName == "Notepad" and _title_matches(w.Name or "", name):
            return w
    return None


def _document(auto, win):
    doc = win.DocumentControl(searchDepth=12)
    if not doc.Exists(2):
        raise ToolError(ErrorCode.TARGET_NOT_FOUND, "Notepad document area not found")
    return doc


def read_tab_text(name: str) -> str | None:
    """Read the text of ORION's tab `name`, or None if it is not the active tab of any window."""
    with _uia() as auto:
        win = find_our_window(auto, name)
        if win is None:
            return None
        return _norm_text(_document(auto, win).GetTextPattern().DocumentRange.GetText(-1))


def _require_windows():
    if sys.platform != "win32":
        raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, "Notepad tools are Windows-only")


class PathArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=260)


class SetTextArgs(PathArgs):
    text: str = Field(max_length=200_000)


class Out(BaseModel):
    path: str
    title: str = ""
    text: str | None = None
    sha256: str | None = None
    evidence: str


# --- notepad.open_file ---------------------------------------------------------------

class OpenFileTool(Tool[PathArgs, Out]):
    spec = ToolSpec(
        id="notepad.open_file", version="1.0", description="Open a workspace text file in Notepad.",
        input_model=PathArgs, output_model=Out,
        permissions=frozenset({Permission.APP_LAUNCH, Permission.FILES_READ}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=20, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="a Notepad window whose active tab is this file appears",
    )

    def run(self, args: PathArgs, ctx: ToolContext) -> Out:
        _require_windows()
        p = resolve_in_workspace(ctx.workspace, args.path)
        if not p.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.path!r} in workspace")
        if ctx.token.is_cancelled:
            raise ToolError(ErrorCode.CANCELLED, "cancelled before opening Notepad")
        subprocess.Popen([NOTEPAD, str(p)], shell=False, close_fds=True)
        with _uia() as auto:
            while time.monotonic() < ctx.deadline - 0.3:
                win = find_our_window(auto, p.name)
                if win is not None:
                    return Out(path=rel_display(ctx.workspace, p), title=win.Name,
                               evidence=f"Notepad shows '{win.Name}'")
                if ctx.token.wait(0.3):
                    raise ToolError(ErrorCode.CANCELLED, "cancelled while waiting for Notepad")
        raise ToolError(ErrorCode.VERIFICATION_FAILED, f"Notepad did not show {p.name} as the active tab")


# --- notepad.read_text -----------------------------------------------------------------

class ReadTextTool(Tool[PathArgs, Out]):
    spec = ToolSpec(
        id="notepad.read_text", version="1.0",
        description="Read the text Notepad shows for a workspace file ORION opened (active tab only).",
        input_model=PathArgs, output_model=Out, permissions=frozenset({Permission.APP_CONTROL}),
        side_effect=SideEffect.READ_ONLY, timeout_s=10, idempotency=Idempotency.IDEMPOTENT,
        verification="text read through UI Automation from the matching tab", max_retries=1,
    )

    def run(self, args: PathArgs, ctx: ToolContext) -> Out:
        _require_windows()
        p = resolve_in_workspace(ctx.workspace, args.path)
        text = read_tab_text(p.name)
        if text is None:
            raise ToolError(ErrorCode.TARGET_NOT_FOUND,
                            f"{p.name} is not the active Notepad tab; ORION will not read other tabs")
        digest = hashlib.sha256(text.encode()).hexdigest()
        return Out(path=rel_display(ctx.workspace, p), text=text, sha256=digest,
                   evidence=f"Notepad shows {len(text)} characters for {p.name}")


# --- notepad.set_text ------------------------------------------------------------------

class SetTextTool(Tool[SetTextArgs, Out]):
    spec = ToolSpec(
        id="notepad.set_text", version="1.0",
        description="Replace the text of a workspace file open in Notepad and save it (old version backed up).",
        input_model=SetTextArgs, output_model=Out,
        permissions=frozenset({Permission.APP_CONTROL, Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=20, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the saved file on disk equals the text, and Notepad shows the same text",
    )

    def run(self, args: SetTextArgs, ctx: ToolContext) -> Out:
        _require_windows()
        p = resolve_in_workspace(ctx.workspace, args.path)
        if not p.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.path!r} in workspace")
        backups = Path(os.path.realpath(ctx.workspace)) / BACKUP_DIR
        backups.mkdir(exist_ok=True)
        backup = backups / f"{time.strftime('%Y%m%d-%H%M%S')}_{p.name}"
        shutil.copy2(p, backup)
        want = _norm_text(args.text)
        with _uia() as auto:
            win = find_our_window(auto, p.name)
            if win is None:
                raise ToolError(ErrorCode.STALE_STATE,
                                f"{p.name} is no longer the active Notepad tab; nothing was typed")
            if ctx.token.is_cancelled:
                raise ToolError(ErrorCode.CANCELLED, "cancelled before changing the text")
            doc = _document(auto, win)
            doc.GetValuePattern().SetValue(args.text)
            # Save: re-check that our tab is still active, then Ctrl+S to the document control only.
            if find_our_window(auto, p.name) is None:
                raise ToolError(ErrorCode.STALE_STATE, "active tab changed before saving; not saved")
            doc.SendKeys("{Ctrl}s", waitTime=0.2)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if _norm_text(p.read_text(encoding="utf-8-sig", errors="replace")) == want:
                    shown = _norm_text(doc.GetTextPattern().DocumentRange.GetText(-1))
                    if shown != want:
                        raise ToolError(ErrorCode.VERIFICATION_FAILED, "saved, but Notepad shows different text")
                    return Out(path=rel_display(ctx.workspace, p), title=win.Name,
                               sha256=hashlib.sha256(want.encode()).hexdigest(),
                               evidence=f"saved {len(want)} characters to {p.name}; disk and screen match; "
                                        f"previous version kept as {BACKUP_DIR}/{backup.name}")
                time.sleep(0.2)
        raise ToolError(ErrorCode.VERIFICATION_FAILED, f"{p.name} on disk does not contain the new text (save failed?)")


# --- notepad.close_tab -----------------------------------------------------------------

class CloseTabTool(Tool[PathArgs, Out]):
    spec = ToolSpec(
        id="notepad.close_tab", version="1.0", description="Close ORION's Notepad tab for a workspace file.",
        input_model=PathArgs, output_model=Out, permissions=frozenset({Permission.APP_CONTROL}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=10, idempotency=Idempotency.IDEMPOTENT,
        verification="no tab for the file remains",
    )

    def run(self, args: PathArgs, ctx: ToolContext) -> Out:
        _require_windows()
        p = resolve_in_workspace(ctx.workspace, args.path)
        with _uia() as auto:
            closed = 0
            for w in auto.GetRootControl().GetChildren():
                if w.ClassName != "Notepad":
                    continue
                tab = w.TabItemControl(searchDepth=8, SubName=p.name)
                if tab.Exists(0.5) and (tab.Name or "").lower().startswith(p.name.lower()):
                    tab.ButtonControl(AutomationId="CloseButton").GetInvokePattern().Invoke()
                    closed += 1
            time.sleep(0.5)
            still = [w for w in auto.GetRootControl().GetChildren() if w.ClassName == "Notepad"
                     and w.TabItemControl(searchDepth=8, SubName=p.name).Exists(0)]
        if still:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, f"a tab for {p.name} is still open")
        return Out(path=rel_display(ctx.workspace, p), evidence=f"closed {closed} Notepad tab(s) for {p.name}")


def notepad_tools() -> list[Tool]:
    return [OpenFileTool(), ReadTextTool(), SetTextTool(), CloseTabTool()]
