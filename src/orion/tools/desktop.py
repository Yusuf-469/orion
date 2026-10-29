"""Desktop tools: see and operate allowed Windows apps through UI Automation (like a screen reader does).

desktop.look  - numbered list of the buttons, fields, menus and text in an allowed app's window
desktop.click - press a control by its number (Invoke / Toggle / Select / Expand, else a checked mouse click)
desktop.type  - set the text of a field by its number, read back

Only apps on the allowlist are visible to these tools (default: Calculator, Paint and ORION's own demo app);
the user can add more in orion.toml. Notepad keeps its own stricter tools (it may show the user's own tabs).
Controls whose names mean sending, buying or deleting are never pressed here.
"""

from __future__ import annotations

import ctypes
import re
import sys
import time
from ctypes import wintypes
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.web.session import CONSEQUENTIAL_WORDS

# app name -> how to recognise its top-level window
DESKTOP_APPS: dict[str, dict[str, str]] = {
    "calculator": {"title": r"^Calculator$"},
    "paint": {"title": r"- Paint$"},
    "canvas demo": {"title": r"^ORION Canvas Demo$"},
}
_FRAME = {"Minimize", "Maximize", "Restore", "Close", "Close Calculator", "Minimize Calculator",
          "Maximize Calculator"}
_SKIP_TYPES = {"WindowControl", "PaneControl", "TitleBarControl", "GroupControl", "CustomControl",
               "ScrollBarControl", "ThumbControl", "SeparatorControl"}
_SENDS = re.compile(rf"\b({CONSEQUENTIAL_WORDS})\b", re.I)
MAX_ITEMS = 150


class _Snap:
    """The last look: ref -> how to find that control again."""
    items: dict[int, dict[str, Any]] = {}
    app: str = ""


def _find_window(auto, app: str):
    spec = DESKTOP_APPS.get(app.lower())
    if spec is None:
        raise ToolError(ErrorCode.PERMISSION_DENIED,
                        f"{app!r} is not an allowed desktop app (allowed: {', '.join(DESKTOP_APPS)})")
    wins = [w for w in auto.GetRootControl().GetChildren() if re.search(spec["title"], w.Name or "")]
    if not wins:
        raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no {app} window is open (open it first with app.launch)")
    return wins[0]


def _walk(auto, win):
    for c, depth in auto.WalkControl(win, maxDepth=16):
        if c.ControlTypeName in _SKIP_TYPES and not c.Name:
            continue
        if c.ControlTypeName in ("WindowControl", "TitleBarControl") or c.Name in _FRAME:
            continue
        if c.GetParentControl() and c.GetParentControl().ControlTypeName == "TitleBarControl":
            continue
        r = c.BoundingRectangle
        if r.width() <= 0 or r.height() <= 0 or c.IsOffscreen:
            continue
        yield c


def _value(auto, c) -> str | None:
    try:
        p = c.GetPattern(auto.PatternId.ValuePattern)
        return p.Value if p else None
    except Exception:  # noqa: BLE001
        return None


_ACTION_PATTERNS = ("InvokePattern", "TogglePattern", "SelectionItemPattern", "ExpandCollapsePattern",
                    "ValuePattern")


def _useful(auto, c) -> bool:
    """Keep what a person can act on or needs to read; drop labels inside buttons and decoration."""
    if any(c.GetPattern(getattr(auto.PatternId, p)) for p in _ACTION_PATTERNS):
        return True
    if c.ControlTypeName == "TextControl":
        parent = c.GetParentControl()
        return not (parent and parent.ControlTypeName in ("ButtonControl", "ListItemControl", "MenuItemControl",
                                                          "TabItemControl", "HyperlinkControl"))
    return c.ControlTypeName in ("ButtonControl", "MenuItemControl", "TabItemControl", "ListItemControl",
                                 "HyperlinkControl", "CheckBoxControl", "RadioButtonControl", "EditControl")


def _describe(auto, c, ref: int) -> dict[str, Any]:
    role = c.ControlTypeName.replace("Control", "").lower()
    item: dict[str, Any] = {"ref": ref, "role": role, "name": (c.Name or "")[:120]}
    if c.AutomationId and not c.AutomationId.isdigit() and len(c.AutomationId) < 40:
        item["id"] = c.AutomationId
    v = _value(auto, c)
    if v is not None:
        item["value"] = v[:200]
    try:
        tp = c.GetPattern(auto.PatternId.TogglePattern)
        if tp:
            item["checked"] = tp.ToggleState == 1
    except Exception:  # noqa: BLE001
        pass
    if not c.IsEnabled:
        item["disabled"] = True
    if role in ("button", "menuitem", "hyperlink") and _SENDS.search(item["name"]):
        item["consequential"] = True
    return item


def _refind(auto, win, crit: dict[str, Any]):
    best, best_d = None, 1e9
    for c in _walk(auto, win):
        if c.Name == crit["name"] and c.ControlTypeName == crit["type"] and c.AutomationId == crit["aid"]:
            r = c.BoundingRectangle
            d = abs(r.left - crit["rect"][0]) + abs(r.top - crit["rect"][1])
            if d < best_d:
                best, best_d = c, d
    if best is None:
        raise ToolError(ErrorCode.STALE_STATE, "that control is no longer there; use desktop.look again")
    return best


class LookArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str = Field(min_length=1, max_length=60)


class LookOut(BaseModel):
    app: str
    title: str
    elements: list[dict[str, Any]]
    evidence: str


class DesktopLookTool(Tool[LookArgs, LookOut]):
    spec = ToolSpec(id="desktop.look", version="1.0",
                    description="Look at an allowed app's window (calculator, paint, canvas demo): numbered buttons, "
                                "fields, menus and text. Use the numbers with desktop.click / desktop.type.",
                    input_model=LookArgs, output_model=LookOut, permissions=frozenset({Permission.APP_CONTROL}),
                    side_effect=SideEffect.READ_ONLY, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
                    verification="controls read live from UI Automation", max_retries=1)

    def run(self, args: LookArgs, ctx: ToolContext) -> LookOut:
        if sys.platform != "win32":
            raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, "desktop tools are Windows-only")
        from orion.tools.windows.notepad import _uia
        with _uia() as auto:
            win = _find_window(auto, args.app)
            items, crit = [], {}
            for c in _walk(auto, win):
                if not c.Name and _value(auto, c) is None:
                    continue
                if not _useful(auto, c):
                    continue
                ref = len(items) + 1
                items.append(_describe(auto, c, ref))
                r = c.BoundingRectangle
                crit[ref] = {"name": c.Name, "type": c.ControlTypeName, "aid": c.AutomationId,
                             "rect": (r.left, r.top), "item": items[-1]}
                if len(items) >= MAX_ITEMS:
                    break
            _Snap.items, _Snap.app = crit, args.app.lower()
            return LookOut(app=args.app, title=win.Name, elements=items,
                           evidence=f"'{win.Name}': {len(items)} controls")


class RefArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: int = Field(ge=1, le=10_000)


class ActOut(BaseModel):
    detail: str
    evidence: str


def _crit(ref: int) -> dict[str, Any]:
    c = _Snap.items.get(ref)
    if c is None:
        raise ToolError(ErrorCode.STALE_STATE, f"no control {ref} in the last desktop.look; look first")
    return c


class DesktopClickTool(Tool[RefArgs, ActOut]):
    spec = ToolSpec(id="desktop.click", version="1.0",
                    description="Press a button, menu item, tab or list item in an allowed app by its number.",
                    input_model=RefArgs, output_model=ActOut, permissions=frozenset({Permission.APP_CONTROL}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.NON_IDEMPOTENT,
                    verification="the control's pattern call succeeds; the app's new state is read on the next look")

    def precheck(self, args: RefArgs) -> None:
        c = _crit(args.ref)
        if c["item"].get("consequential"):
            raise ToolError(ErrorCode.PERMISSION_DENIED,
                            f"'{c['name']}' would send, buy or delete something; ORION does not press it here")

    def run(self, args: RefArgs, ctx: ToolContext) -> ActOut:
        self.precheck(args)
        crit = _crit(args.ref)
        from orion.tools.windows.notepad import _uia
        with _uia() as auto:
            win = _find_window(auto, _Snap.app)
            c = _refind(auto, win, crit)
            how = None
            for pid, call, label in ((auto.PatternId.InvokePattern, lambda p: p.Invoke(), "invoked"),
                                     (auto.PatternId.TogglePattern, lambda p: p.Toggle(), "toggled"),
                                     (auto.PatternId.SelectionItemPattern, lambda p: p.Select(), "selected"),
                                     (auto.PatternId.ExpandCollapsePattern, lambda p: p.Expand(), "expanded")):
                p = c.GetPattern(pid)
                if p:
                    call(p)
                    how = label
                    break
            if how is None:   # no pattern: a mouse click, only if this app's window is really under the point
                r = c.BoundingRectangle
                x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
                user32 = ctypes.WinDLL("user32")
                user32.WindowFromPoint.restype = wintypes.HWND
                user32.GetAncestor.restype = wintypes.HWND
                h = user32.WindowFromPoint(wintypes.POINT(x, y))
                if int(user32.GetAncestor(h, 2) or 0) != win.NativeWindowHandle:
                    raise ToolError(ErrorCode.STALE_STATE, f"another window covers '{c.Name}'; did not click")
                win.SetActive()
                auto.Click(x, y, waitTime=0.1)
                how = f"clicked at ({x},{y})"
            time.sleep(0.3)
        return ActOut(detail=how, evidence=f"{how} '{crit['name']}' in {_Snap.app}")


class TypeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: int = Field(ge=1, le=10_000)
    text: str = Field(max_length=5_000)


class DesktopTypeTool(Tool[TypeArgs, ActOut]):
    spec = ToolSpec(id="desktop.type", version="1.0",
                    description="Set the text of a field in an allowed app by its number (replaces its text).",
                    input_model=TypeArgs, output_model=ActOut, permissions=frozenset({Permission.APP_CONTROL}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
                    verification="the field's value is read back")

    def run(self, args: TypeArgs, ctx: ToolContext) -> ActOut:
        crit = _crit(args.ref)
        from orion.tools.windows.notepad import _uia
        with _uia() as auto:
            win = _find_window(auto, _Snap.app)
            c = _refind(auto, win, crit)
            p = c.GetPattern(auto.PatternId.ValuePattern)
            if not p or p.IsReadOnly:
                raise ToolError(ErrorCode.INVALID_INPUT,
                                f"'{crit['name']}' is not an editable field. To press it use desktop.click; to type "
                                f"into the app like a keyboard use desktop.keys"
                                + ("; for sums use calculator.compute" if _Snap.app == "calculator" else ""))
            p.SetValue(args.text)
            got = p.Value
        if got.strip() != args.text.strip():
            raise ToolError(ErrorCode.VERIFICATION_FAILED, f"field shows {got[:60]!r} after typing")
        return ActOut(detail=got[:200], evidence=f"typed {len(args.text)} characters into '{crit['name']}'; read back")


class KeysArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str = Field(min_length=1, max_length=60)
    keys: str = Field(min_length=1, max_length=500)


# Named keys allowed inside {braces}. No Windows key, no Alt+F4, no Ctrl+Alt combinations.
_NAMED = {"enter", "tab", "esc", "escape", "backspace", "delete", "up", "down", "left", "right", "home", "end",
          "space", "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+z", "ctrl+y", "ctrl+s", "f2"}


class DesktopKeysTool(Tool[KeysArgs, ActOut]):
    spec = ToolSpec(id="desktop.keys", version="1.0",
                    description="Type keys into an allowed app's window, like a keyboard: plain text, plus named keys "
                                "in braces such as {Enter}, {Tab}, {Esc}, {Backspace}. E.g. Calculator: '2400*0.15='.",
                    input_model=KeysArgs, output_model=ActOut, permissions=frozenset({Permission.APP_CONTROL}),
                    side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.NON_IDEMPOTENT,
                    verification="keys go only to the allowed app, checked to be in front first")

    def precheck(self, args: KeysArgs) -> None:
        for name in re.findall(r"\{([^}]*)\}", args.keys):
            if name.lower() not in _NAMED:
                raise ToolError(ErrorCode.PERMISSION_DENIED, f"key {{{name}}} is not allowed "
                                                             f"(allowed: {', '.join(sorted(_NAMED))})")

    def run(self, args: KeysArgs, ctx: ToolContext) -> ActOut:
        self.precheck(args)
        from orion.tools.windows.notepad import _uia
        conv = {"enter": "{Enter}", "tab": "{Tab}", "esc": "{Esc}", "escape": "{Esc}", "backspace": "{Back}",
                "delete": "{Delete}", "up": "{Up}", "down": "{Down}", "left": "{Left}", "right": "{Right}",
                "home": "{Home}", "end": "{End}", "space": " ", "f2": "{F2}", "ctrl+a": "{Ctrl}a",
                "ctrl+c": "{Ctrl}c", "ctrl+v": "{Ctrl}v", "ctrl+z": "{Ctrl}z", "ctrl+y": "{Ctrl}y", "ctrl+s": "{Ctrl}s"}
        parts = re.split(r"(\{[^}]*\})", args.keys)
        with _uia() as auto:
            win = _find_window(auto, args.app)
            win.SetActive()
            time.sleep(0.3)
            user32 = ctypes.WinDLL("user32")
            user32.GetForegroundWindow.restype = wintypes.HWND
            for part in parts:
                if not part:
                    continue
                if int(user32.GetForegroundWindow() or 0) != win.NativeWindowHandle:
                    raise ToolError(ErrorCode.STALE_STATE, f"{args.app} is no longer in front; stopped typing")
                if part.startswith("{"):
                    auto.SendKeys(conv[part[1:-1].lower()], interval=0.02, waitTime=0.05)
                else:   # literal text: escape the library's own special characters
                    auto.SendKeys(re.sub(r"([{}])", r"{\1}", part), interval=0.02, waitTime=0.05)
            time.sleep(0.3)
        return ActOut(detail=args.keys, evidence=f"typed {args.keys!r} into {args.app} (checked it was in front)")


def desktop_tools() -> list[Tool]:
    return [DesktopLookTool(), DesktopClickTool(), DesktopTypeTool(), DesktopKeysTool()]
