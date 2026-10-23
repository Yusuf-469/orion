"""Executors.

An Action wraps a callable: a simulated step, or (Stage 2+) a registered tool
call via `orion.execution.tool_action`. The dry-run guarantee is structural:
DryRunExecutor has no code path that calls `fn`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from orion.orchestration.cancel import Cancelled, CancelToken


class ActionError(Exception):
    """A structured action failure.

    blocked: refused before running (permission denied / not confirmed).
    uncertain: the action may or may not have taken effect; a human must review.
    """

    def __init__(self, message: str, *, blocked: bool = False, uncertain: bool = False):
        super().__init__(message)
        self.blocked = blocked
        self.uncertain = uncertain


@dataclass(frozen=True)
class Action:
    name: str
    fn: Callable[[CancelToken], str]   # returns evidence text
    simulated: bool = True
    preview: Callable[[], str] | None = None   # dry-run description; must not execute anything


@dataclass(frozen=True)
class ActionResult:
    executed: bool
    ok: bool
    cancelled: bool
    evidence: str
    blocked: bool = False
    uncertain: bool = False


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
        except ActionError as e:
            return ActionResult(executed=not e.blocked, ok=False, cancelled=False, evidence=str(e),
                                blocked=e.blocked, uncertain=e.uncertain)
        except Exception as e:  # noqa: BLE001 - every failure becomes a structured result
            return ActionResult(executed=True, ok=False, cancelled=False,
                                evidence=f"{type(e).__name__}: {e}")
        prefix = "simulated: " if action.simulated else ""
        return ActionResult(executed=True, ok=True, cancelled=False, evidence=prefix + evidence)


class DryRunExecutor:
    dry_run = True

    def execute(self, action: Action, token: CancelToken) -> ActionResult:
        detail = f"; {action.preview()}" if action.preview else ""
        return ActionResult(executed=False, ok=True, cancelled=False,
                            evidence=f"dry-run: '{action.name}' planned, not executed{detail}")
