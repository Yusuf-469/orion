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


# --- anywhere on the PC ------------------------------------------------------------
# Relative paths stay confined to the workspace (above). An absolute local path may name
# any file on the PC; whether touching it needs the user's yes is decided by the runtime
# and policy engine (see `outside_reason` / `protected_reason`), never by the model.

def is_absolute(path: str) -> bool:
    w = PureWindowsPath(path)
    return bool(w.drive and w.root)


def resolve_absolute(path: str) -> Path:
    if "\x00" in path:
        raise _deny(path, "NUL byte")
    w = PureWindowsPath(path)
    if not (w.drive and w.root):
        raise _deny(path, "expected a full path such as C:\\Users\\me\\file.txt")
    if w.drive.startswith("\\\\"):
        raise _deny(path, "network (UNC) paths are not allowed: opening one can leak your Windows credentials")
    if ":" in path[len(w.drive):]:
        raise _deny(path, "':' not allowed after the drive letter (alternate data streams)")
    for p in w.parts[1:]:
        if p == "..":
            raise _deny(path, "'..' not allowed")
        if _RESERVED.match(p):
            raise _deny(path, f"reserved device name {p!r}")
        if p.endswith(".") or p.endswith(" "):
            raise _deny(path, "names ending in '.' or ' ' are aliased by Windows")
    return Path(os.path.realpath(path))


def resolve_path(workspace: Path, path: str, *, allow_trash: bool = False) -> Path:
    """A full path names a file anywhere on the PC; anything else is inside the workspace."""
    if is_absolute(path):
        return resolve_absolute(path)
    return resolve_in_workspace(workspace, path, allow_trash=allow_trash)


def _under(p: Path, root: str) -> bool:
    a, b = os.path.normcase(str(p)), os.path.normcase(os.path.realpath(root)).rstrip("\\/")
    return a == b or a.startswith(b + os.sep)


def inside_workspace(workspace: Path, p: Path) -> bool:
    return _under(p, str(workspace))


def display(workspace: Path, p: Path) -> str:
    return rel_display(workspace, p) if inside_workspace(workspace, p) else str(p)


def outside_reason(workspace: Path, p: Path, verb: str) -> str | None:
    if inside_workspace(workspace, p):
        return None
    return f"{verb} outside the ORION workspace: {p}"


def protected_reason(p: Path) -> str | None:
    """Locations where a change can break Windows or touch another person's files."""
    env = os.environ
    system = [env.get("SystemRoot", r"C:\Windows"), env.get("ProgramFiles", r"C:\Program Files"),
              env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), env.get("ProgramData", r"C:\ProgramData")]
    for root in system:
        if root and _under(p, root):
            return f"{p} is inside a Windows system folder ({root})"
    parts = [x.lower() for x in p.parts]
    if len(parts) >= 2 and parts[1] in ("system volume information", "$recycle.bin", "recovery", "boot"):
        return f"{p} is a protected Windows location"
    if len(p.parts) == 1:
        return f"{p} is the root of a drive"
    users = os.path.dirname(env.get("USERPROFILE", r"C:\Users\me"))
    if _under(p, users) and not _under(p, env.get("USERPROFILE", "")) and not _under(p, os.path.join(users, "Public")):
        return f"{p} is inside another user's profile"
    return None
