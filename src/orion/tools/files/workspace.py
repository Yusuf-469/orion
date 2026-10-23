"""Confine every file path to the authorized workspace folder.

Paths are given relative to the workspace. Anything that could name a location
outside it, or alias a different file on Windows, is rejected before touching
the disk; the final check compares the fully resolved real path (symlinks and
junctions followed) against the resolved workspace.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from orion.tools.errors import ErrorCode, ToolError

TRASH_DIR = ".orion_trash"

_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?$", re.IGNORECASE)


def _deny(path: str, why: str) -> ToolError:
    return ToolError(ErrorCode.PERMISSION_DENIED, f"path {path!r} rejected: {why}", path=path)


def resolve_in_workspace(workspace: Path, rel: str, *, allow_trash: bool = False) -> Path:
    if not rel or not rel.strip():
        raise ToolError(ErrorCode.INVALID_INPUT, "empty path")
    if "\x00" in rel:
        raise _deny(rel, "NUL byte")
    win = PureWindowsPath(rel)
    if win.is_absolute() or win.drive or win.root or PurePosixPath(rel).is_absolute():
        raise _deny(rel, "absolute paths, drives and UNC paths are not allowed")
    if ":" in rel:
        raise _deny(rel, "':' not allowed (drive letters / alternate data streams)")
    parts = win.parts
    for p in parts:
        if p == "..":
            raise _deny(rel, "'..' not allowed")
        if _RESERVED.match(p):
            raise _deny(rel, f"reserved device name {p!r}")
        if p != "." and (p.endswith(".") or p.endswith(" ")):
            raise _deny(rel, "names ending in '.' or ' ' are aliased by Windows")
    if not allow_trash and parts and parts[0].lower() == TRASH_DIR:
        raise _deny(rel, f"{TRASH_DIR} is managed by ORION")

    ws_real = os.path.realpath(workspace)
    target = os.path.realpath(os.path.join(ws_real, *parts))
    ws_norm, t_norm = os.path.normcase(ws_real), os.path.normcase(target)
    if t_norm != ws_norm and not t_norm.startswith(ws_norm.rstrip("\\/") + os.sep):
        raise _deny(rel, "resolves outside the workspace (symlink or junction?)")
    return Path(target)


def rel_display(workspace: Path, p: Path) -> str:
    return Path(os.path.relpath(p, os.path.realpath(workspace))).as_posix()
