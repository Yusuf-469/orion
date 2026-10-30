"""Bounded file tools. Each one verifies its effect by reading the disk afterwards."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.files.workspace import (
    TRASH_DIR, display, outside_reason, protected_reason, rel_display, resolve_path,
)

PATH_HELP = "Relative paths are inside the workspace; a full path (C:\\...) reaches any file on the PC."

MAX_BYTES = 5_000_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_cancel(ctx: ToolContext) -> None:
    if ctx.token.is_cancelled:
        raise ToolError(ErrorCode.CANCELLED, "cancelled before the change was made")


# --- files.read ------------------------------------------------------------------

class ReadArgs(_Strict):
    path: str = Field(min_length=1, max_length=260)
    max_bytes: int = Field(default=1_000_000, ge=1, le=MAX_BYTES)


class ReadOut(BaseModel):
    path: str
    size: int
    sha256: str
    text: str
    evidence: str


class ReadFileTool(Tool[ReadArgs, ReadOut]):
    spec = ToolSpec(
        id="files.read", version="1.1", description=f"Read a UTF-8 text file. {PATH_HELP}",
        input_model=ReadArgs, output_model=ReadOut, permissions=frozenset({Permission.FILES_READ}),
        side_effect=SideEffect.READ_ONLY, timeout_s=10, idempotency=Idempotency.IDEMPOTENT,
        verification="returns the bytes actually read and their SHA-256", max_retries=1,
    )

    def run(self, args: ReadArgs, ctx: ToolContext) -> ReadOut:
        p = resolve_path(ctx.workspace, args.path)
        if not p.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.path!r}")
        size = p.stat().st_size
        if size > args.max_bytes:
            raise ToolError(ErrorCode.INVALID_INPUT, f"file is {size} bytes, over max_bytes={args.max_bytes}")
        data = p.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ToolError(ErrorCode.INVALID_INPUT, "file is not UTF-8 text") from None
        digest = hashlib.sha256(data).hexdigest()
        rel = display(ctx.workspace, p)
        return ReadOut(path=rel, size=len(data), sha256=digest, text=text,
                       evidence=f"read {len(data)} bytes from {rel} (sha256 {digest[:12]})")


# --- files.write_new -------------------------------------------------------------

class WriteArgs(_Strict):
    path: str = Field(min_length=1, max_length=260)
    content: str = Field(max_length=MAX_BYTES)


class WriteOut(BaseModel):
    path: str
    size: int
    sha256: str
    evidence: str


class WriteNewFileTool(Tool[WriteArgs, WriteOut]):
    spec = ToolSpec(
        id="files.write_new", version="1.1",
        description=f"Create a NEW UTF-8 text file. Never overwrites. {PATH_HELP} Outside the workspace it asks first.",
        input_model=WriteArgs, output_model=WriteOut, permissions=frozenset({Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=10, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="re-reads the file and compares SHA-256 with the intended content",
    )

    def escalation(self, args: WriteArgs, workspace: Path) -> str | None:
        return outside_reason(workspace, resolve_path(workspace, args.path), "creates a file")

    def protected(self, args: WriteArgs, workspace: Path) -> str | None:
        return protected_reason(resolve_path(workspace, args.path))

    def describe(self, args: WriteArgs) -> tuple[str, str]:
        return (f"Create the new file '{args.path}'",
                "A new file is written there. Nothing existing is overwritten.")

    def run(self, args: WriteArgs, ctx: ToolContext) -> WriteOut:
        p = resolve_path(ctx.workspace, args.path)
        data = args.content.encode("utf-8")
        _check_cancel(ctx)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "xb") as f:   # exclusive create: fails if the file exists
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            raise ToolError(ErrorCode.INVALID_INPUT, f"{args.path!r} already exists; write_new never overwrites") from None
        want, got = hashlib.sha256(data).hexdigest(), _sha256(p)
        if want != got:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, "file on disk differs from intended content",
                            expected=want, actual=got)
        rel = display(ctx.workspace, p)
        return WriteOut(path=rel, size=len(data), sha256=got,
                        evidence=f"created {rel}, {len(data)} bytes; re-read sha256 {got[:12]} matches")


# --- files.copy ------------------------------------------------------------------

class CopyArgs(_Strict):
    src: str = Field(min_length=1, max_length=260)
    dst: str = Field(min_length=1, max_length=260)


class CopyOut(BaseModel):
    src: str
    dst: str
    sha256: str
    evidence: str


class CopyFileTool(Tool[CopyArgs, CopyOut]):
    spec = ToolSpec(
        id="files.copy", version="1.1",
        description=f"Copy a file to a NEW path. Never overwrites. {PATH_HELP} A destination outside the workspace asks first.",
        input_model=CopyArgs, output_model=CopyOut,
        permissions=frozenset({Permission.FILES_READ, Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="SHA-256 of the copy equals SHA-256 of the source",
    )

    def escalation(self, args: CopyArgs, workspace: Path) -> str | None:
        return outside_reason(workspace, resolve_path(workspace, args.dst), "copies a file to")

    def protected(self, args: CopyArgs, workspace: Path) -> str | None:
        return protected_reason(resolve_path(workspace, args.dst))

    def describe(self, args: CopyArgs) -> tuple[str, str]:
        return (f"Copy '{args.src}' to '{args.dst}'",
                "A new copy is written at the destination. The original is not changed and nothing is overwritten.")

    def run(self, args: CopyArgs, ctx: ToolContext) -> CopyOut:
        src = resolve_path(ctx.workspace, args.src)
        dst = resolve_path(ctx.workspace, args.dst)
        if not src.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.src!r}")
        if dst.exists():
            raise ToolError(ErrorCode.INVALID_INPUT, f"{args.dst!r} already exists; copy never overwrites")
        if src.stat().st_size > MAX_BYTES:
            raise ToolError(ErrorCode.INVALID_INPUT, f"source is over {MAX_BYTES} bytes")
        _check_cancel(ctx)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as fi, open(dst, "xb") as fo:
            shutil.copyfileobj(fi, fo)
        a, b = _sha256(src), _sha256(dst)
        if a != b:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, "copy differs from source", expected=a, actual=b)
        rs, rd = display(ctx.workspace, src), display(ctx.workspace, dst)
        return CopyOut(src=rs, dst=rd, sha256=b, evidence=f"copied {rs} -> {rd}; sha256 {b[:12]} matches")


# --- files.list ------------------------------------------------------------------

class ListArgs(_Strict):
    path: str = Field(default=".", min_length=1, max_length=260)


class Entry(BaseModel):
    name: str
    kind: Literal["file", "dir"]
    size: int | None


class ListOut(BaseModel):
    path: str
    entries: list[Entry]
    truncated: bool
    evidence: str


class ListDirTool(Tool[ListArgs, ListOut]):
    spec = ToolSpec(
        id="files.list", version="1.1", description=f"List a directory. {PATH_HELP}",
        input_model=ListArgs, output_model=ListOut, permissions=frozenset({Permission.FILES_READ}),
        side_effect=SideEffect.READ_ONLY, timeout_s=10, idempotency=Idempotency.IDEMPOTENT,
        verification="returns the directory listing as read from disk", max_retries=1,
    )
    LIMIT = 500

    def run(self, args: ListArgs, ctx: ToolContext) -> ListOut:
        p = resolve_path(ctx.workspace, args.path)
        if not p.is_dir():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no directory {args.path!r}")
        entries: list[Entry] = []
        truncated = False
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if child.name == TRASH_DIR and p == Path(os.path.realpath(ctx.workspace)):
                continue
            if len(entries) >= self.LIMIT:
                truncated = True
                break
            try:
                is_dir = child.is_dir()
                size = None if is_dir else child.stat().st_size
            except OSError:   # locked or access-denied entries outside the workspace
                continue
            entries.append(Entry(name=child.name, kind="dir" if is_dir else "file", size=size))
        rel = display(ctx.workspace, p)
        return ListOut(path=rel, entries=entries, truncated=truncated,
                       evidence=f"listed {len(entries)} entries in {rel}" + (" (truncated)" if truncated else ""))


# --- files.delete ----------------------------------------------------------------

class DeleteArgs(_Strict):
    path: str = Field(min_length=1, max_length=260)


class DeleteOut(BaseModel):
    path: str
    moved_to: str
    evidence: str


class DeleteFileTool(Tool[DeleteArgs, DeleteOut]):
    spec = ToolSpec(
        id="files.delete", version="1.1",
        description=f"Delete a file by moving it to {TRASH_DIR}/ in the workspace (always asks first). {PATH_HELP}",
        input_model=DeleteArgs, output_model=DeleteOut, permissions=frozenset({Permission.FILES_DELETE}),
        side_effect=SideEffect.CONSEQUENTIAL, timeout_s=30, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="source path no longer exists and the trash copy has the same SHA-256",
    )

    def protected(self, args: DeleteArgs, workspace: Path) -> str | None:
        return protected_reason(resolve_path(workspace, args.path))

    def describe(self, args: DeleteArgs) -> tuple[str, str]:
        return (f"Delete the file '{args.path}'",
                f"The file is moved to {TRASH_DIR}/ inside the ORION workspace. ORION has no undo command; "
                f"restoring it means moving it back by hand.")

    def run(self, args: DeleteArgs, ctx: ToolContext) -> DeleteOut:
        p = resolve_path(ctx.workspace, args.path)
        if not p.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.path!r}")
        before = _sha256(p)
        trash = Path(os.path.realpath(ctx.workspace)) / TRASH_DIR
        trash.mkdir(exist_ok=True)
        dest = trash / f"{time.strftime('%Y%m%d-%H%M%S')}_{time.monotonic_ns() % 10**6:06d}_{p.name}"
        _check_cancel(ctx)
        shutil.move(str(p), str(dest))   # os.replace within a drive; copy-and-remove across drives
        if p.exists() or not dest.is_file() or _sha256(dest) != before:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, "move to trash could not be verified",
                            source_exists=p.exists(), trash=str(dest))
        rel, rel_dest = display(ctx.workspace, p), rel_display(ctx.workspace, dest)
        return DeleteOut(path=rel, moved_to=rel_dest,
                         evidence=f"{rel} gone; moved to {rel_dest} with matching sha256 {before[:12]}")


def file_tools() -> list[Tool]:
    return [ReadFileTool(), WriteNewFileTool(), CopyFileTool(), ListDirTool(), DeleteFileTool()]
