"""Document tools: CSV create and summarize. New files only; each verifies by reading back."""

from __future__ import annotations

import csv
import io
import os

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.files.workspace import rel_display, resolve_in_workspace, resolve_path


def _new_file(ctx: ToolContext, rel: str):
    p = resolve_in_workspace(ctx.workspace, rel)
    if p.exists():
        raise ToolError(ErrorCode.INVALID_INPUT, f"{rel!r} already exists; ORION never overwrites")
    if ctx.token.is_cancelled:
        raise ToolError(ErrorCode.CANCELLED, "cancelled before writing")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write_exclusive(p, text: str) -> None:
    with open(p, "x", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


class WriteCsvArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=260, pattern=r"(?i)\.csv$")
    headers: list[str] = []
    rows: list[list[str]] = Field(min_length=1, max_length=100_000)


class Out(BaseModel):
    path: str
    evidence: str


class WriteCsvTool(Tool[WriteCsvArgs, Out]):
    spec = ToolSpec(
        id="docs.write_csv", version="1.0", description="Create a NEW CSV file from a header and rows.",
        input_model=WriteCsvArgs, output_model=Out, permissions=frozenset({Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=15, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the file is parsed back and equals the header and rows",
    )

    def run(self, args: WriteCsvArgs, ctx: ToolContext) -> Out:
        p = _new_file(ctx, args.path)
        buf = io.StringIO()
        w = csv.writer(buf)
        if args.headers:
            w.writerow(args.headers)
        w.writerows(args.rows)
        _write_exclusive(p, buf.getvalue())
        back = list(csv.reader(open(p, encoding="utf-8", newline="")))
        expect = ([args.headers] if args.headers else []) + args.rows
        if back != expect:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, "CSV read back differs from what was written")
        return Out(path=rel_display(ctx.workspace, p),
                   evidence=f"wrote {len(args.rows)} rows to {p.name}; read back and matched")


class SummarizeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    src: str = Field(min_length=1, max_length=260, pattern=r"(?i)\.csv$")
    dst: str = Field(min_length=1, max_length=260)


def _number(s: str) -> float | None:
    try:
        return float(s.replace(",", "").replace("₹", "").replace("$", "").strip())
    except ValueError:
        return None


def summarize(header: list[str], rows: list[list[str]]) -> str:
    lines = [f"Rows: {len(rows)}", f"Columns: {', '.join(header)}"]
    for i, name in enumerate(header):
        nums = [_number(r[i]) for r in rows if i < len(r)]
        if nums and all(n is not None for n in nums):
            total = sum(nums)
            lines.append(f"{name}: total {total:g}, average {total / len(nums):g}, "
                         f"min {min(nums):g}, max {max(nums):g}")
    return "\n".join(lines) + "\n"


class SummarizeCsvTool(Tool[SummarizeArgs, Out]):
    spec = ToolSpec(
        id="docs.summarize_csv", version="1.0",
        description="Write a NEW text summary of a CSV (row count, columns, totals of numeric columns).",
        input_model=SummarizeArgs, output_model=Out,
        permissions=frozenset({Permission.FILES_READ, Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=15, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the summary file is read back and its row count matches the CSV",
    )

    def run(self, args: SummarizeArgs, ctx: ToolContext) -> Out:
        src = resolve_path(ctx.workspace, args.src)   # the CSV may be anywhere on the PC
        if not src.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.src!r}")
        data = list(csv.reader(open(src, encoding="utf-8-sig", newline="")))
        if len(data) < 2:
            raise ToolError(ErrorCode.INVALID_INPUT, f"{args.src!r} has no data rows under a header")
        header, rows = data[0], data[1:]
        text = summarize(header, rows)
        dst = _new_file(ctx, args.dst)
        _write_exclusive(dst, text)
        if dst.read_text(encoding="utf-8") != text or f"Rows: {len(rows)}" not in text:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, "summary read back differs")
        return Out(path=rel_display(ctx.workspace, dst),
                   evidence=f"summarized {len(rows)} rows of {src.name} into {dst.name}")


def document_tools() -> list[Tool]:
    return [WriteCsvTool(), SummarizeCsvTool()]
