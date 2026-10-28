"""calculator.compute: press Calculator's buttons through UI Automation and read the answer.

Uses its OWN new Calculator window (never one the user has open) and closes it afterwards.
Buttons are pressed with UIA Invoke (no mouse, no keystrokes). The displayed answer is checked
against ORION's own calculation; a mismatch is a failure, not a result.
"""

from __future__ import annotations

import ast
import operator
import os
import re
import subprocess
import sys
import time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orion.tools.base import Idempotency, Permission, SideEffect, Tool, ToolContext, ToolSpec
from orion.tools.errors import ErrorCode, ToolError

CALC = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "calc.exe")
_EXPR = re.compile(r"^\d+(\.\d+)?([+\-*/]\d+(\.\d+)?){1,20}$")
_KEYS = {"+": "plusButton", "-": "minusButton", "*": "multiplyButton", "/": "divideButton",
         ".": "decimalSeparatorButton", **{str(d): f"num{d}Button" for d in range(10)}}
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def normalize(expr: str) -> str:
    return (expr.replace(" ", "").replace("x", "*").replace("X", "*").replace("×", "*").replace("÷", "/")
            .replace(",", ""))


def evaluate(expr: str) -> float:
    """Safe arithmetic with normal precedence (what Windows 11 Calculator shows)."""
    def ev(n):
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        raise ValueError("unsupported expression")
    return float(ev(ast.parse(expr, mode="eval").body))


class CalcArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(min_length=3, max_length=120)

    @field_validator("expression")
    @classmethod
    def _plain_arithmetic(cls, v: str) -> str:
        if not _EXPR.match(normalize(v)):
            raise ValueError("only numbers with + - * / (e.g. 1250*12+300) are supported")
        return v


class CalcOut(BaseModel):
    expression: str
    result: str
    display: str
    evidence: str


def _number(display: str) -> float | None:
    m = re.search(r"-?[\d,]*\.?\d+(?:e[+-]?\d+)?", display.replace("Display is", ""), re.I)
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


class CalculatorComputeTool(Tool[CalcArgs, CalcOut]):
    spec = ToolSpec(
        id="calculator.compute", version="1.0",
        description="Work out a sum by pressing Windows Calculator's buttons and reading its display.",
        input_model=CalcArgs, output_model=CalcOut,
        permissions=frozenset({Permission.APP_LAUNCH, Permission.APP_CONTROL}),
        side_effect=SideEffect.REVERSIBLE, timeout_s=30, idempotency=Idempotency.IDEMPOTENT,
        verification="the number Calculator displays equals ORION's own calculation", max_retries=1,
    )

    def run(self, args: CalcArgs, ctx: ToolContext) -> CalcOut:
        if sys.platform != "win32":
            raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, "Calculator is Windows-only")
        from orion.tools.windows.notepad import _uia
        expr = normalize(args.expression)
        try:
            expected = evaluate(expr)
        except ZeroDivisionError:
            raise ToolError(ErrorCode.INVALID_INPUT, "division by zero") from None
        with _uia() as auto:
            before = {w.NativeWindowHandle for w in auto.GetRootControl().GetChildren()}
            subprocess.Popen([CALC], shell=False, close_fds=True)
            win = None
            while time.monotonic() < ctx.deadline - 5:
                win = next((w for w in auto.GetRootControl().GetChildren()
                            if w.NativeWindowHandle not in before and w.Name == "Calculator"), None)
                if win is not None:
                    break
                if ctx.token.wait(0.2):
                    raise ToolError(ErrorCode.CANCELLED, "cancelled while Calculator was starting")
            if win is None:
                raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, "no new Calculator window appeared")
            try:
                def press(key: str) -> None:
                    btn = win.ButtonControl(searchDepth=12, AutomationId=key)
                    if not btn.Exists(3):
                        raise ToolError(ErrorCode.TARGET_NOT_FOUND, f"Calculator button {key} not found "
                                        f"(is Calculator in Standard mode?)")
                    btn.GetInvokePattern().Invoke()

                press("clearButton")
                for ch in expr:
                    if ctx.token.is_cancelled:
                        raise ToolError(ErrorCode.CANCELLED, "cancelled while pressing buttons")
                    press(_KEYS[ch])
                press("equalButton")
                display = ""
                for _ in range(20):
                    display = win.Control(searchDepth=12, AutomationId="CalculatorResults").Name or ""
                    if _number(display) is not None:
                        break
                    time.sleep(0.1)
            finally:
                win.GetWindowPattern().Close()   # ORION's own window
        shown = _number(display)
        if shown is None:
            raise ToolError(ErrorCode.VERIFICATION_FAILED, f"could not read a number from Calculator: {display!r}")
        if abs(shown - expected) > 1e-9 * max(1.0, abs(expected)):
            raise ToolError(ErrorCode.VERIFICATION_FAILED,
                            f"Calculator shows {shown:g} but {args.expression} = {expected:g}")
        result = f"{shown:g}" if abs(shown) < 1e15 else str(shown)
        return CalcOut(expression=args.expression, result=result, display=display,
                       evidence=f"pressed {len(expr) + 2} buttons; Calculator shows {result} "
                                f"(matches ORION's own calculation); its window was closed")


def calculator_tools() -> list[Tool]:
    return [CalculatorComputeTool()]
