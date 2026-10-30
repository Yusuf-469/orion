"""File tools against a temporary workspace (real disk I/O inside pytest's tmp dir only)."""

import os
import subprocess
from pathlib import Path

import pytest

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import ErrorCode, Permission, ToolError, ToolRegistry
from orion.tools.files import TRASH_DIR, file_tools, resolve_in_workspace

pytestmark = pytest.mark.safety


class Approve:
    def __init__(self):
        self.asked = []

    def confirm(self, req, token):
        self.asked.append(req)
        return True


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "workspace"
    w.mkdir()
    return w


def runtime(ws, granted=frozenset(Permission), confirmer=None):
    reg = ToolRegistry()
    for t in file_tools():
        reg.register(t)
    return ToolRuntime(reg, PolicyEngine(granted), confirmer or DenyAllConfirmer(), ws)


def call(rt, tool_id, **args):
    return rt.execute(ToolCall(tool_id=tool_id, args=args), CancelToken())


# --- path confinement --------------------------------------------------------------

BAD_PATHS = [
    "..\\secret.txt", "../secret.txt", "a/../../secret.txt", "C:\\Windows\\win.ini", "C:secret.txt",
    "\\\\server\\share\\x", "/etc/passwd", "\\Windows\\win.ini", "notes.txt:hidden", "CON", "nul.txt",
    "com1.log", "dir./x.txt", "trailing ", f"{TRASH_DIR}/x.txt", "a\x00b",
]


@pytest.mark.parametrize("bad", BAD_PATHS)
def test_paths_outside_or_aliasing_rejected(ws, bad):
    with pytest.raises(ToolError) as e:
        resolve_in_workspace(ws, bad)
    assert e.value.code in (ErrorCode.PERMISSION_DENIED, ErrorCode.INVALID_INPUT)


@pytest.mark.parametrize("bad,code", [("..\\outside.txt", ErrorCode.PERMISSION_DENIED),
                                      ("C:\\Users\\Public\\orion_test.txt", ErrorCode.CONFIRMATION_REQUIRED)])
def test_write_outside_workspace_never_touches_disk_without_a_yes(ws, bad, code):
    r = call(runtime(ws), "files.write_new", path=bad, content="x")
    assert r.error_code == code
    assert not (ws.parent / "outside.txt").exists()
    assert not Path("C:/Users/Public/orion_test.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_junction_escape_blocked(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = ws / "link"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    r = call(runtime(ws), "files.read", path="link/secret.txt")
    assert r.error_code == ErrorCode.PERMISSION_DENIED
    r = call(runtime(ws), "files.write_new", path="link/new.txt", content="x")
    assert r.error_code == ErrorCode.PERMISSION_DENIED and not (outside / "new.txt").exists()


def test_normal_nested_path_allowed(ws):
    assert resolve_in_workspace(ws, "reports/2026/summary.txt").name == "summary.txt"


# --- behaviour and verification ---------------------------------------------------------

def test_write_then_read_roundtrip_with_evidence(ws):
    rt = runtime(ws)
    w = call(rt, "files.write_new", path="out/report.txt", content="héllo\nworld\n")
    assert w.ok and "matches" in w.evidence
    r = call(rt, "files.read", path="out/report.txt")
    assert r.ok and r.output["text"] == "héllo\nworld\n" and r.output["sha256"] == w.output["sha256"]
    assert (ws / "out" / "report.txt").read_bytes() == "héllo\nworld\n".encode()


def test_write_never_overwrites(ws):
    (ws / "keep.txt").write_text("original")
    r = call(runtime(ws), "files.write_new", path="keep.txt", content="new")
    assert r.error_code == ErrorCode.INVALID_INPUT and (ws / "keep.txt").read_text() == "original"


def test_copy_verifies_and_never_overwrites(ws):
    (ws / "a.txt").write_text("data")
    (ws / "b.txt").write_text("other")
    rt = runtime(ws)
    assert call(rt, "files.copy", src="a.txt", dst="c.txt").ok
    assert (ws / "c.txt").read_text() == "data"
    assert call(rt, "files.copy", src="a.txt", dst="b.txt").error_code == ErrorCode.INVALID_INPUT
    assert (ws / "b.txt").read_text() == "other"


def test_list_hides_trash(ws):
    (ws / "x.txt").write_text("1")
    (ws / TRASH_DIR).mkdir()
    r = call(runtime(ws), "files.list")
    assert [e["name"] for e in r.output["entries"]] == ["x.txt"]


def test_missing_file_is_target_not_found(ws):
    assert call(runtime(ws), "files.read", path="nope.txt").error_code == ErrorCode.TARGET_NOT_FOUND


def test_binary_file_not_read_as_text(ws):
    (ws / "b.bin").write_bytes(b"\xff\xfe\x00\x81")
    assert call(runtime(ws), "files.read", path="b.bin").error_code == ErrorCode.INVALID_INPUT


# --- delete: permission, confirmation, recoverability --------------------------------------

def test_delete_denied_without_permission(ws):
    (ws / "x.txt").write_text("1")
    rt = runtime(ws, granted=frozenset({Permission.FILES_READ, Permission.FILES_WRITE}))
    assert call(rt, "files.delete", path="x.txt").error_code == ErrorCode.PERMISSION_DENIED
    assert (ws / "x.txt").exists()


def test_delete_declined_keeps_file(ws):
    (ws / "x.txt").write_text("1")
    assert call(runtime(ws), "files.delete", path="x.txt").error_code == ErrorCode.CONFIRMATION_REQUIRED
    assert (ws / "x.txt").exists()


def test_delete_confirmed_moves_to_trash(ws):
    (ws / "x.txt").write_text("keep me")
    conf = Approve()
    r = call(runtime(ws, confirmer=conf), "files.delete", path="x.txt")
    assert r.ok and not (ws / "x.txt").exists()
    assert "x.txt" in conf.asked[0].action and TRASH_DIR in conf.asked[0].consequence
    trashed = list((ws / TRASH_DIR).iterdir())
    assert len(trashed) == 1 and trashed[0].read_text() == "keep me"


def test_cancelled_write_makes_no_file(ws):
    tok = CancelToken()
    tok.cancel("test")
    r = runtime(ws).execute(ToolCall(tool_id="files.write_new", args={"path": "x.txt", "content": "1"}), tok)
    assert r.error_code == ErrorCode.CANCELLED and not (ws / "x.txt").exists()
