"""Policy engine v1: allow / confirm / deny, decided outside any model.

Inputs are the *registered* tool spec and the permissions the user granted in
config. Nothing in the call itself (arguments, labels, requester) can lower
the side-effect category. Consequential tools always require confirmation;
there is deliberately no setting to turn that off.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from orion.orchestration.cancel import CancelToken
from orion.tools.base import Permission, SideEffect, ToolSpec


class Decision(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: str
    tool_id: str
    side_effect: SideEffect | None


@dataclass(frozen=True)
class PolicyEngine:
    granted: frozenset[Permission]
    confirm_reversible: bool = False

    def decide(self, spec: ToolSpec) -> PolicyDecision:
        missing = spec.permissions - self.granted
        if missing:
            names = ", ".join(sorted(missing))
            return PolicyDecision(Decision.DENY, f"permission not granted: {names}", spec.id, spec.side_effect)
        if spec.side_effect is SideEffect.CONSEQUENTIAL:
            return PolicyDecision(Decision.CONFIRM, "consequential action requires confirmation",
                                  spec.id, spec.side_effect)
        if spec.side_effect is SideEffect.REVERSIBLE and self.confirm_reversible:
            return PolicyDecision(Decision.CONFIRM, "configured to confirm local changes",
                                  spec.id, spec.side_effect)
        return PolicyDecision(Decision.ALLOW, f"{spec.side_effect} with granted permissions",
                              spec.id, spec.side_effect)


@dataclass(frozen=True)
class ConfirmationRequest:
    """What the user is asked (spec 11.4: action, target, consequence)."""
    tool_id: str
    side_effect: SideEffect
    action: str
    consequence: str


class Confirmer(Protocol):
    def confirm(self, request: ConfirmationRequest, token: CancelToken) -> bool:
        """Ask the user. One answer covers exactly one call. Return False if declined or cancelled."""
        ...


class DenyAllConfirmer:
    """Default when no UI is attached: every confirmation is declined."""

    def confirm(self, request: ConfirmationRequest, token: CancelToken) -> bool:
        return False
