"""Verification engine v1: evaluates checks by observing the environment (read-only).

A check never trusts a tool's own report; it reads the disk or enumerates
windows itself.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from orion.planner.schemas import (
    AppWindowOpen, FileAbsent, FileContains, FileExists, FilesIdentical, NotepadShows,
)
from orion.tools.errors import ToolError
from orion.tools.files.workspace import resolve_in_workspace


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    evidence: str


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Verifier:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def check(self, c) -> CheckResult:
        try:
            return self._check(c)
        except ToolError as e:
            return CheckResult(False, f"{c.kind}: {e.message}")
        except OSError as e:
            return CheckResult(False, f"{c.kind}: {type(e).__name__}: {e}")

    def check_all(self, checks) -> tuple[bool, list[CheckResult]]:
        results = [self.check(c) for c in checks]
        return all(r.ok for r in results), results

    def _check(self, c) -> CheckResult:
        ws = self.workspace
        if isinstance(c, FileExists):
            p = resolve_in_workspace(ws, c.path)
            ok = p.is_file()
            return CheckResult(ok, f"file_exists {c.path}: " + (f"yes, {p.stat().st_size} bytes" if ok else "NO"))
        if isinstance(c, FileAbsent):
            p = resolve_in_workspace(ws, c.path)
            ok = not p.exists()
            return CheckResult(ok, f"file_absent {c.path}: " + ("absent" if ok else "STILL PRESENT"))
        if isinstance(c, FileContains):
            p = resolve_in_workspace(ws, c.path)
            if not p.is_file():
                return CheckResult(False, f"file_contains {c.path}: file missing")
            text = p.read_bytes().decode("utf-8-sig", errors="replace")
            ok = (c.text.lower() in text.lower()) if c.ignore_case else (c.text in text)
            return CheckResult(ok, f"file_contains {c.path}: " + ("text found" if ok else "text NOT found"))
        if isinstance(c, FilesIdentical):
            a, b = resolve_in_workspace(ws, c.a), resolve_in_workspace(ws, c.b)
            if not (a.is_file() and b.is_file()):
                return CheckResult(False, f"files_identical {c.a} {c.b}: missing "
                                          f"{', '.join(x for x, p in ((c.a, a), (c.b, b)) if not p.is_file())}")
            ha, hb = _sha(a), _sha(b)
            return CheckResult(ha == hb, f"files_identical {c.a} {c.b}: " +
                               (f"sha256 {ha[:12]} both" if ha == hb else "DIFFERENT"))
        if isinstance(c, NotepadShows):
            if sys.platform != "win32":
                return CheckResult(False, "notepad_shows: unsupported on this OS")
            from orion.tools.windows.notepad import _norm_text, read_tab_text
            p = resolve_in_workspace(ws, c.path)
            if not p.is_file():
                return CheckResult(False, f"notepad_shows {c.path}: file missing")
            shown = read_tab_text(p.name)
            if shown is None:
                return CheckResult(False, f"notepad_shows {c.path}: not the active Notepad tab")
            disk = _norm_text(p.read_text(encoding="utf-8-sig", errors="replace"))
            ok = shown.rstrip("\n") == disk.rstrip("\n")
            return CheckResult(ok, f"notepad_shows {c.path}: " +
                               (f"screen matches disk ({len(disk)} chars)" if ok else "screen DIFFERS from disk"))
        if isinstance(c, AppWindowOpen):
            if sys.platform != "win32":
                return CheckResult(False, "app_window_open: unsupported on this OS")
            from orion.tools.windows.launch import ALLOWLIST, _matches
            from orion.tools.windows.win32 import visible_windows
            wins = [w for w in visible_windows() if _matches(ALLOWLIST[c.app], w)]
            return CheckResult(bool(wins), f"app_window_open {c.app}: " +
                               (f"'{wins[0].title}'" if wins else "no window"))
        return CheckResult(False, f"unknown check {c!r}")
