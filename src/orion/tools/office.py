"""Office through its own automation interface (COM), not by clicking: faster and exact.

Idea from Microsoft UFO (MIT), which drives Word/Excel through their APIs where it can. ORION's rules:
- every call starts its OWN hidden Office instance (DispatchEx), so files the user has open are untouched,
  and quits it afterwards;
- macros are forced off (AutomationSecurity = 3): a workbook's macros are untrusted code;
- reads open read-only; writes go to a NEW file (never overwrite) and are read back to verify;
- paths follow ORION's file rules (outside the workspace asks first; system folders ask twice).
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.files.workspace import display, outside_reason, protected_reason, resolve_path

FORCE_DISABLE_MACROS = 3   # msoAutomationSecurityForceDisable
MAX_CELLS = 5_000


@contextmanager
def _office(prog_id: str):
    if sys.platform != "win32":
        raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, "Office automation is Windows-only")
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = None
    try:
        try:
            app = win32com.client.DispatchEx(prog_id)   # a new, private instance
        except Exception as e:  # noqa: BLE001
            raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, f"{prog_id.split('.')[0]} is not available: {e}") from None
        if prog_id == "PowerPoint.Application":   # PowerPoint cannot hide its app window; files open windowless
            app.DisplayAlerts = 1                  # ppAlertsNone
        else:
            app.Visible = False
            app.DisplayAlerts = 0
        app.AutomationSecurity = FORCE_DISABLE_MACROS
        yield app
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:  # noqa: BLE001
                pass
        pythoncom.CoUninitialize()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("|", "/").replace("\n", " ")


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return "(empty)"
    w = max(len(r) for r in rows)
    lines = ["| " + " | ".join(_cell(c) for c in (rows[0] + [""] * (w - len(rows[0])))) + " |",
             "|" + "---|" * w]
    lines += ["| " + " | ".join(_cell(c) for c in (r + [""] * (w - len(r)))) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _values(rng) -> list[list[Any]]:
    v = rng.Value
    if not isinstance(v, tuple):
        return [[v]]
    return [list(r) for r in v]


# --- excel.read --------------------------------------------------------------------------------

class ExcelReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=260, pattern=r"(?i)\.(xlsx|xlsm|xls|csv)$")
    sheet: str | None = Field(default=None, max_length=100, description="sheet name; default the first sheet")
    range: str | None = Field(default=None, max_length=30, pattern=r"^[A-Za-z]{1,3}\d{1,7}(:[A-Za-z]{1,3}\d{1,7})?$",
                              description="e.g. A1:D20; default the used range")


class ExcelReadOut(BaseModel):
    path: str
    sheet: str
    sheets: list[str]
    range: str
    table: str
    untrusted: bool = True
    evidence: str


class ExcelReadTool(Tool[ExcelReadArgs, ExcelReadOut]):
    spec = ToolSpec(
        id="excel.read", version="1.0",
        description="Read a spreadsheet (.xlsx/.xls/.csv) with Excel: a sheet or range as a table, with computed "
                    "formula values. Relative paths are in the workspace; a full path reads anywhere.",
        input_model=ExcelReadArgs, output_model=ExcelReadOut, permissions=frozenset({Permission.FILES_READ}),
        side_effect=SideEffect.READ_ONLY, timeout_s=60, idempotency=Idempotency.IDEMPOTENT,
        verification="values read by Excel itself from the file, opened read-only", max_retries=1)

    def run(self, args: ExcelReadArgs, ctx: ToolContext) -> ExcelReadOut:
        p = resolve_path(ctx.workspace, args.path)
        if not p.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.path!r}")
        with _office("Excel.Application") as xl:
            wb = xl.Workbooks.Open(str(p), UpdateLinks=0, ReadOnly=True)
            try:
                names = [s.Name for s in wb.Worksheets]
                if args.sheet and args.sheet not in names:
                    raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no sheet {args.sheet!r} (sheets: {', '.join(names)})")
                ws = wb.Worksheets(args.sheet or names[0])
                rng = ws.Range(args.range) if args.range else ws.UsedRange
                if rng.Count > MAX_CELLS:
                    raise ToolError(ErrorCode.INVALID_INPUT, f"{rng.Count} cells is too many; give a smaller range")
                rows, addr = _values(rng), rng.Address.replace("$", "")
            finally:
                wb.Close(SaveChanges=False)
        shown = display(ctx.workspace, p)
        return ExcelReadOut(path=shown, sheet=args.sheet or names[0], sheets=names, range=addr, table=_table(rows),
                            evidence=f"read {len(rows)} rows from {shown} [{args.sheet or names[0]}!{addr}] with Excel")


# --- excel.write -------------------------------------------------------------------------------

class ExcelWriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=260, pattern=r"(?i)\.xlsx$", description="NEW workbook to create")
    rows: list[list[str | float | int | None]] = Field(min_length=1, max_length=500,
                                                       description="cells by row; text starting with = is a formula")
    sheet: str = Field(default="Sheet1", min_length=1, max_length=31)
    source: str | None = Field(default=None, max_length=260, pattern=r"(?i)\.(xlsx|xlsm|xls|csv)$",
                               description="optional existing workbook to start from (it is not changed)")
    start: str = Field(default="A1", pattern=r"^[A-Za-z]{1,3}\d{1,7}$")


class ExcelWriteOut(BaseModel):
    path: str
    table: str
    evidence: str


class ExcelWriteTool(Tool[ExcelWriteArgs, ExcelWriteOut]):
    spec = ToolSpec(
        id="excel.write", version="1.0",
        description="Create a NEW Excel workbook (never overwrites): cells by row, formulas like =SUM(B2:B9) are "
                    "computed by Excel. Optionally start from a copy of an existing workbook (source).",
        input_model=ExcelWriteArgs, output_model=ExcelWriteOut, permissions=frozenset({Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=90, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the saved file is reopened and its cells read back")

    def escalation(self, args: ExcelWriteArgs, workspace: Path) -> str | None:
        return outside_reason(workspace, resolve_path(workspace, args.path), "creates a workbook")

    def protected(self, args: ExcelWriteArgs, workspace: Path) -> str | None:
        return protected_reason(resolve_path(workspace, args.path))

    def describe(self, args: ExcelWriteArgs) -> tuple[str, str]:
        return f"Create the workbook '{args.path}'", "A new file is saved there; nothing existing is overwritten."

    def run(self, args: ExcelWriteArgs, ctx: ToolContext) -> ExcelWriteOut:
        out = resolve_path(ctx.workspace, args.path)
        if out.exists():
            raise ToolError(ErrorCode.INVALID_INPUT, f"{args.path!r} already exists; ORION never overwrites")
        src = resolve_path(ctx.workspace, args.source) if args.source else None
        if src is not None and not src.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.source!r}")
        if ctx.token.is_cancelled:
            raise ToolError(ErrorCode.CANCELLED, "cancelled before writing")
        width = max(len(r) for r in args.rows)
        grid = [list(r) + [None] * (width - len(r)) for r in args.rows]
        out.parent.mkdir(parents=True, exist_ok=True)
        with _office("Excel.Application") as xl:
            wb = xl.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True) if src else xl.Workbooks.Add()
            try:
                names = [s.Name for s in wb.Worksheets]
                if args.sheet in names:
                    ws = wb.Worksheets(args.sheet)
                elif src is None and len(names) == 1:
                    ws = wb.Worksheets(1)
                    ws.Name = args.sheet
                else:
                    ws = wb.Worksheets.Add()
                    ws.Name = args.sheet
                r0, c0 = ws.Range(args.start).Row, ws.Range(args.start).Column
                rng = ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + len(grid) - 1, c0 + width - 1))
                rng.Formula = tuple(tuple("" if c is None else c for c in r) for r in grid)
                xl.Calculate()
                wb.SaveAs(str(out), FileFormat=51)   # 51 = .xlsx (no macros)
            finally:
                wb.Close(SaveChanges=False)
            check = xl.Workbooks.Open(str(out), UpdateLinks=0, ReadOnly=True)
            try:
                cws = check.Worksheets(args.sheet)
                got = _values(cws.Range(cws.Cells(r0, c0), cws.Cells(r0 + len(grid) - 1, c0 + width - 1)))
            finally:
                check.Close(SaveChanges=False)
        for r, row in enumerate(grid):   # plain values must come back as written; formulas show their result
            for c, want in enumerate(row):
                if want is None or (isinstance(want, str) and want.startswith("=")):
                    continue
                if _cell(got[r][c]) != _cell(want):
                    raise ToolError(ErrorCode.VERIFICATION_FAILED, f"cell {r + 1},{c + 1} reads {got[r][c]!r}, "
                                                                   f"expected {want!r}")
        errors = [v for row in got for v in row if isinstance(v, int) and v < -2_000_000_000]   # #DIV/0!, #NAME? ...
        shown = display(ctx.workspace, out)
        return ExcelWriteOut(path=shown, table=_table(got),
                             evidence=f"created {shown} ({len(grid)} rows); reopened and read back"
                                      + (f"; {len(errors)} formula errors" if errors else ""))


# --- office.export_pdf ------------------------------------------------------------------------

class PdfArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    src: str = Field(min_length=1, max_length=260, pattern=r"(?i)\.(docx|doc|xlsx|xls|pptx|ppt)$")
    out: str = Field(min_length=1, max_length=260, pattern=r"(?i)\.pdf$")


class PdfOut(BaseModel):
    path: str
    pages: int | None
    evidence: str


class ExportPdfTool(Tool[PdfArgs, PdfOut]):
    spec = ToolSpec(
        id="office.export_pdf", version="1.0",
        description="Save a Word, Excel or PowerPoint file as a NEW PDF using Office itself (exact layout).",
        input_model=PdfArgs, output_model=PdfOut, permissions=frozenset({Permission.FILES_READ, Permission.FILES_WRITE}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=120, idempotency=Idempotency.NON_IDEMPOTENT,
        verification="the PDF exists and its pages are counted")

    def escalation(self, args: PdfArgs, workspace: Path) -> str | None:
        return outside_reason(workspace, resolve_path(workspace, args.out), "creates a PDF")

    def protected(self, args: PdfArgs, workspace: Path) -> str | None:
        return protected_reason(resolve_path(workspace, args.out))

    def describe(self, args: PdfArgs) -> tuple[str, str]:
        return f"Save '{args.src}' as the PDF '{args.out}'", "A new PDF is written; the original is not changed."

    def run(self, args: PdfArgs, ctx: ToolContext) -> PdfOut:
        src, out = resolve_path(ctx.workspace, args.src), resolve_path(ctx.workspace, args.out)
        if not src.is_file():
            raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no file {args.src!r}")
        if out.exists():
            raise ToolError(ErrorCode.INVALID_INPUT, f"{args.out!r} already exists; ORION never overwrites")
        out.parent.mkdir(parents=True, exist_ok=True)
        ext = src.suffix.lower()
        if ext in (".docx", ".doc"):
            with _office("Word.Application") as w:
                d = w.Documents.Open(str(src), ReadOnly=True, AddToRecentFiles=False)
                try:
                    d.ExportAsFixedFormat(str(out), 17)   # wdExportFormatPDF
                finally:
                    d.Close(SaveChanges=0)
        elif ext in (".xlsx", ".xls"):
            with _office("Excel.Application") as xl:
                wb = xl.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True)
                try:
                    wb.ExportAsFixedFormat(0, str(out))   # xlTypePDF
                finally:
                    wb.Close(SaveChanges=False)
        else:
            with _office("PowerPoint.Application") as pp:
                pres = pp.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
                try:
                    pres.SaveAs(str(out), 32)   # ppSaveAsPDF
                finally:
                    pres.Close()
        if not out.is_file() or os.path.getsize(out) == 0:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, "Office did not produce the PDF")
        try:
            from pypdf import PdfReader
            pages: int | None = len(PdfReader(str(out)).pages)
        except Exception:  # noqa: BLE001
            pages = None
        shown = display(ctx.workspace, out)
        return PdfOut(path=shown, pages=pages, evidence=f"created {shown}" + (f", {pages} page(s)" if pages else ""))


def office_tools() -> list[Tool]:
    return [ExcelReadTool(), ExcelWriteTool(), ExportPdfTool()]
