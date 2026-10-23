"""Task and step status machine (statuses as listed in the 12-week plan, Week 4)."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"


TERMINAL = frozenset({Status.SUCCEEDED, Status.FAILED, Status.CANCELLED, Status.SKIPPED})

_ALLOWED: dict[Status, frozenset[Status]] = {
    Status.PENDING: frozenset({Status.READY, Status.BLOCKED, Status.CANCELLED, Status.SKIPPED}),
    Status.READY: frozenset({Status.RUNNING, Status.BLOCKED, Status.CANCELLED, Status.SKIPPED}),
    Status.RUNNING: frozenset({
        Status.SUCCEEDED, Status.FAILED, Status.CANCELLED, Status.SKIPPED,
        Status.WAITING_FOR_USER, Status.BLOCKED, Status.NEEDS_REVIEW,
    }),
    Status.WAITING_FOR_USER: frozenset({Status.RUNNING, Status.CANCELLED}),
    Status.BLOCKED: frozenset({Status.READY, Status.FAILED, Status.CANCELLED}),
    Status.NEEDS_REVIEW: frozenset({Status.SUCCEEDED, Status.FAILED, Status.CANCELLED}),
}


class InvalidTransition(ValueError):
    pass


def check_transition(current: Status, new: Status) -> None:
    if new not in _ALLOWED.get(current, frozenset()):
        raise InvalidTransition(f"{current} -> {new} is not allowed")
