"""Executors.

Stage 1 has no tool registry yet; an Action wraps a callable. Stage 2 replaces
the callable with a registered, schema-validated tool call, but the dry-run
guarantee stays structural: DryRunExecutor has no code path that calls `fn`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from orion.orchestration.cancel import Cancelled, CancelToken


@dataclass(frozen=True)
class Action:
    name: str
    fn: Callable[[CancelToken], str]   # returns evidence text
    simulated: bool = True


@dataclass(frozen=True)
class ActionResult:
    executed: bool
    ok: bool
    cancelled: bool
    evidence: str


class Executor(Protocol):
    dry_run: bool

    def execute(self, action: Action, token: CancelToken) -> ActionResult: ...


class RealExecutor:
    dry_run = False

    def execute(self, action: Action, token: CancelToken) -> ActionResult:
        token.raise_if_cancelled()
        try:
            evidence = action.fn(token)
        except Cancelled as e:
            return ActionResult(executed=True, ok=False, cancelled=True,
                                evidence=f"interrupted: {e}")
        except Exception as e:  # noqa: BLE001 - every failure becomes a structured result
            return ActionResult(executed=True, ok=False, cancelled=False,
                                evidence=f"{type(e).__name__}: {e}")
        prefix = "simulated: " if action.simulated else ""
        return ActionResult(executed=True, ok=True, cancelled=False, evidence=prefix + evidence)


class DryRunExecutor:
    dry_run = True

    def execute(self, action: Action, token: CancelToken) -> ActionResult:
        return ActionResult(executed=False, ok=True, cancelled=False,
                            evidence=f"dry-run: '{action.name}' planned, not executed")
