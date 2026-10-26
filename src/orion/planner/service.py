"""Planner interface and the single entry point that always validates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from orion.planner.schemas import Goal, Plan
from orion.planner.validator import PlanIssue, validate_plan
from orion.policy.engine import PolicyEngine
from orion.tools.registry import ToolRegistry


@dataclass
class Proposal:
    """What a planner proposes. Nothing here is trusted until validated."""
    goal: Goal | None
    plan: Plan | None
    message: str = ""
    metrics: dict[str, int] = field(default_factory=dict)


@dataclass
class PlanResult:
    status: Literal["ok", "clarify", "unsupported", "invalid"]
    goal: Goal | None
    plan: Plan | None
    issues: list[PlanIssue]
    message: str
    planner: str
    metrics: dict[str, int] = field(default_factory=dict)

    @property
    def questions(self) -> list[str]:
        return list(self.goal.missing_info) if self.goal else []


class Planner(Protocol):
    name: str

    def propose(self, request: str) -> Proposal: ...


def plan_request(planner: Planner, request: str, registry: ToolRegistry, policy: PolicyEngine,
                 workspace: Path) -> PlanResult:
    p = planner.propose(request)
    if p.goal is not None and p.goal.missing_info:
        return PlanResult("clarify", p.goal, p.plan, [], p.message or "more information needed",
                          planner.name, p.metrics)
    if p.goal is None or p.plan is None:
        return PlanResult("unsupported", p.goal, None, [], p.message, planner.name, p.metrics)
    issues = validate_plan(p.plan, p.goal, registry, policy, workspace)
    status = "invalid" if any(i.severity == "error" for i in issues) else "ok"
    return PlanResult(status, p.goal, p.plan, issues, p.message, planner.name, p.metrics)
