"""Structured error taxonomy (spec section 8.4)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PERMISSION_DENIED = "permission_denied"
    TARGET_NOT_FOUND = "target_not_found"
    STALE_STATE = "stale_state"
    TIMEOUT = "timeout"
    APPLICATION_UNAVAILABLE = "application_unavailable"
    VERIFICATION_FAILED = "verification_failed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


# Errors where the action was refused before running: the step is blocked, not failed.
BLOCKING_CODES = frozenset({ErrorCode.PERMISSION_DENIED, ErrorCode.CONFIRMATION_REQUIRED})


class ToolError(Exception):
    def __init__(self, code: ErrorCode, message: str, **details: Any):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details
