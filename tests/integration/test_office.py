"""Office tools through COM (Excel/Word installed on this PC). Marked `real`: starts hidden Office instances.
Files only in pytest's temp folder."""

import sys

import pytest

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy import DenyAllConfirmer, PolicyEngine
from orion.tools import ErrorCode, Permission, ToolRegistry
from orion.tools.office import office_tools

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]


@pytest.fixture
def call(tmp_path):
    reg = ToolRegistry()
    for t in office_tools():
        reg.register(t)
    rt = ToolRuntime(reg, PolicyEngine(frozenset(Permission)), DenyAllConfirmer(), tmp_path)
    return lambda tool, **a: rt.execute(ToolCall(tool_id=tool, args=a), CancelToken())


def test_write_with_formula_then_read_back(call, tmp_path):
    rows = [["Item", "Price"], ["Aurora X1", 249], ["Nimbus Pro", 199], ["Total", "=SUM(B2:B3)"]]
    w = call("excel.write", path="prices.xlsx", rows=rows)
    assert w.ok, w.error_message
    r = call("excel.read", path="prices.xlsx")
    assert r.ok, r.error_message
    assert "| Total | 448 |" in r.output["table"]          # Excel computed the formula
    assert r.output["sheets"] == ["Sheet1"]


def test_never_overwrites_and_source_stays_unchanged(call, tmp_path):
    assert call("excel.write", path="a.xlsx", rows=[["x", 1]]).ok
    again = call("excel.write", path="a.xlsx", rows=[["y", 2]])
    assert again.error_code == ErrorCode.INVALID_INPUT
    b = call("excel.write", path="b.xlsx", source="a.xlsx", sheet="Notes", rows=[["note"]])
    assert b.ok, b.error_message
    assert call("excel.read", path="a.xlsx").output["sheets"] == ["Sheet1"]
    assert set(call("excel.read", path="b.xlsx").output["sheets"]) == {"Sheet1", "Notes"}


def test_export_excel_and_word_to_pdf(call, tmp_path):
    assert call("excel.write", path="t.xlsx", rows=[["a", "b"], [1, 2]]).ok
    p = call("office.export_pdf", src="t.xlsx", out="t.pdf")
    assert p.ok and p.output["pages"] == 1, p.error_message
    import docx
    d = docx.Document()
    d.add_heading("Report", 0)
    d.save(tmp_path / "r.docx")
    q = call("office.export_pdf", src="r.docx", out="r.pdf")
    assert q.ok and q.output["pages"] == 1, q.error_message
