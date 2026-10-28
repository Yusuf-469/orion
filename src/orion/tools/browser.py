"""Browser tools (Playwright, bundled Chromium, throwaway profile).

Only local pages: an .html file inside the workspace, or http(s) on localhost /
127.0.0.1. Each call starts a fresh headless browser with a temporary profile
(no cookies, no logins, never the user's own browsers). Page text is returned
as untrusted data and is never treated as instructions.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.files.workspace import resolve_in_workspace

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_TEXT = 20_000


def resolve_page(page: str, ctx: ToolContext) -> str:
    """Turn a workspace .html path or a localhost URL into a URL; reject everything else."""
    if "://" in page:
        u = urlparse(page)
        if u.scheme not in ("http", "https") or u.hostname not in _LOCAL_HOSTS:
            raise ToolError(ErrorCode.PERMISSION_DENIED,
                            f"only local pages are allowed (workspace .html or http://localhost); got {page!r}")
        return page
    p = resolve_in_workspace(ctx.workspace, page)
    if not p.exists():   # demo pages live in workspace/pages/
        alt = resolve_in_workspace(ctx.workspace, f"pages/{page}")
        p = alt if alt.exists() else p
    if p.suffix.lower() not in (".html", ".htm"):
        raise ToolError(ErrorCode.INVALID_INPUT, f"{page!r} is not an .html page")
    if not p.is_file():
        raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"no page {page!r} in workspace")
    return p.as_uri()


def _with_page(url: str, ctx: ToolContext, fn):
    from playwright.sync_api import Error as PwError
    from playwright.sync_api import sync_playwright

    if ctx.token.is_cancelled:
        raise ToolError(ErrorCode.CANCELLED, "cancelled before opening the browser")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_context().new_page()   # fresh, empty profile
                page.goto(url, wait_until="load", timeout=15_000)
                return fn(page)
            finally:
                browser.close()
    except PwError as e:
        raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, f"browser error: {str(e).splitlines()[0]}") from None


class TableArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str = Field(min_length=1, max_length=500)
    table_index: int = Field(default=0, ge=0, le=50)


class TableOut(BaseModel):
    page: str
    title: str
    headers: list[str]
    rows: list[list[str]]
    untrusted: bool = True
    evidence: str


class ReadTableTool(Tool[TableArgs, TableOut]):
    spec = ToolSpec(
        id="browser.read_table", version="1.0", description="Read a table from a local web page.",
        input_model=TableArgs, output_model=TableOut, permissions=frozenset({Permission.BROWSER_READ}),
        side_effect=SideEffect.READ_ONLY, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
        verification="cells read from the page's DOM", max_retries=1,
    )

    def run(self, args: TableArgs, ctx: ToolContext) -> TableOut:
        url = resolve_page(args.page, ctx)

        def read(page):
            tables = page.locator("table")
            if tables.count() <= args.table_index:
                raise ToolError(ErrorCode.TARGET_NOT_FOUND,
                                f"page has {tables.count()} table(s); no table #{args.table_index}")
            t = tables.nth(args.table_index)
            headers = [h.strip() for h in t.locator("thead th, tr:first-child th").all_inner_texts()]
            rows = []
            for tr in t.locator("tbody tr, tr:has(td)").all():
                cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
                if cells and cells not in rows:
                    rows.append(cells)
            if not rows:
                raise ToolError(ErrorCode.TARGET_NOT_FOUND, "the table has no data rows")
            return page.title(), headers, rows

        title, headers, rows = _with_page(url, ctx, read)
        return TableOut(page=args.page, title=title, headers=headers, rows=rows,
                        evidence=f"read {len(rows)} rows x {len(headers) or len(rows[0])} columns from '{title}'")


class TextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str = Field(min_length=1, max_length=500)


class TextOut(BaseModel):
    page: str
    title: str
    text: str
    untrusted: bool = True
    evidence: str


class ReadTextTool(Tool[TextArgs, TextOut]):
    spec = ToolSpec(
        id="browser.read_text", version="1.0", description="Read the visible text of a local web page.",
        input_model=TextArgs, output_model=TextOut, permissions=frozenset({Permission.BROWSER_READ}),
        side_effect=SideEffect.READ_ONLY, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
        verification="text read from the page's DOM", max_retries=1,
    )

    def run(self, args: TextArgs, ctx: ToolContext) -> TextOut:
        url = resolve_page(args.page, ctx)
        title, text = _with_page(url, ctx, lambda page: (page.title(), page.locator("body").inner_text()))
        return TextOut(page=args.page, title=title, text=text[:MAX_TEXT],
                       evidence=f"read {min(len(text), MAX_TEXT)} characters from '{title}' (untrusted page text)")


def browser_tools() -> list[Tool]:
    return [ReadTableTool(), ReadTextTool()]
