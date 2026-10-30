"""Tool runtime: validate → authorize → (confirm) → run with timeout/cancel → validate output.

Python cannot kill a thread, so a tool that ignores its token or deadline keeps
running in the background. The runtime stops *waiting* for it and reports the
outcome as uncertain for any tool that is not read-only; it never pretends the
action did not happen.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from orion.observability.logging import redact
from orion.orchestration.cancel import CancelToken
from orion.policy.engine import ConfirmationRequest, Confirmer, Decision, PolicyEngine
from orion.tools.base import Idempotency, SideEffect, ToolContext
from orion.tools.errors import ErrorCode, ToolError
from orion.tools.registry import ToolRegistry

log = logging.getLogger("orion.runtime")

CANCEL_GRACE_S = 0.5
_POLL_S = 0.02
_RETRYABLE = frozenset({ErrorCode.TIMEOUT, ErrorCode.APPLICATION_UNAVAILABLE})


class ToolCall(BaseModel):
    """A request to run a tool. Extra fields (e.g. a self-declared side effect) are rejected."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str
    args: dict[str, Any] = {}


@dataclass
class ToolResult:
    tool_id: str
    ok: bool
    output: dict[str, Any] | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    side_effect_uncertain: bool = False
    attempts: int = 0
    duration_s: float = 0.0
    decision: Decision | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def evidence(self) -> str:
        if self.ok and self.output is not None:
            return str(self.output.get("evidence", self.output))
        return f"{self.error_code}: {self.error_message}"


class ToolRuntime:
    def __init__(self, registry: ToolRegistry, policy: PolicyEngine, confirmer: Confirmer, workspace: Path):
        self.registry = registry
        self.policy = policy
        self.confirmer = confirmer
        self.workspace = workspace

    def preview(self, call: ToolCall) -> str:
        """Dry-run description: what policy would decide. Executes nothing."""
        try:
            tool = self.registry.get(call.tool_id)
            tool.spec.input_model.model_validate(call.args)
        except ToolError as e:
            return f"would fail: {e.code}: {e.message}"
        except ValidationError as e:
            return f"would fail: {ErrorCode.INVALID_INPUT}: {_summarize(e)}"
        d = self._decide(tool, tool.spec.input_model.model_validate(call.args))
        return f"would {d.decision} ({d.reason})"

    def _decide(self, tool, args: BaseModel):
        """Policy on the registered spec, raised (never lowered) by the call's own target."""
        decision = self.policy.decide(tool.spec)
        escalation = getattr(tool, "escalation", None)
        if escalation is not None and decision.decision is not Decision.DENY:
            try:
                decision = self.policy.escalate(decision, escalation(args, self.workspace))
            except ToolError:
                pass   # a bad path is reported by precheck / run, before anything is touched
        return decision

    def execute(self, call: ToolCall, token: CancelToken) -> ToolResult:
        start = time.monotonic()
        result = self._execute(call, token)
        result.duration_s = time.monotonic() - start
        log.info("tool %s -> %s", call.tool_id, "ok" if result.ok else result.error_code,
                 extra={"event": {"kind": "tool_result", "tool_id": call.tool_id, "ok": result.ok,
                                  "error_code": result.error_code, "uncertain": result.side_effect_uncertain,
                                  "attempts": result.attempts, "decision": result.decision}})
        return result

    def _execute(self, call: ToolCall, token: CancelToken) -> ToolResult:
        tid = call.tool_id
        if token.is_cancelled:
            return _fail(tid, ErrorCode.CANCELLED, f"cancelled before start ({token.reason})")
        try:
            tool = self.registry.get(tid)
        except ToolError as e:
            return _fail(tid, e.code, e.message)
        spec = tool.spec
        try:
            args = spec.input_model.model_validate(call.args)
        except ValidationError as e:
            return _fail(tid, ErrorCode.INVALID_INPUT, _summarize(e))

        decision = self._decide(tool, args)
        if decision.decision is Decision.DENY:
            return _fail(tid, ErrorCode.PERMISSION_DENIED, decision.reason, decision=decision.decision)
        precheck = getattr(tool, "precheck", None)   # reject a malformed call before the user is ever asked
        if precheck is not None:
            try:
                precheck(args)
            except ToolError as e:
                return _fail(tid, e.code, e.message, decision=decision.decision)
        if decision.decision is Decision.CONFIRM:
            describe = getattr(tool, "describe", None)
            action, consequence = describe(args) if describe else (f"run {tid}", decision.reason)
            req = ConfirmationRequest(tid, spec.side_effect, redact(action), redact(consequence))
            approved = self.confirmer.confirm(req, token)
            if token.is_cancelled:
                return _fail(tid, ErrorCode.CANCELLED, "cancelled while awaiting confirmation",
                             decision=decision.decision)
            if not approved:
                return _fail(tid, ErrorCode.CONFIRMATION_REQUIRED, "user did not confirm",
                             decision=decision.decision)
            protected = getattr(tool, "protected", None)
            danger = None
            if protected is not None:
                try:
                    danger = protected(args, self.workspace)
                except ToolError:
                    danger = None
            if danger:   # second, explicit yes for system folders and other users' files
                req2 = ConfirmationRequest(tid, spec.side_effect, redact(f"Are you sure? {action}"),
                                           redact(f"{danger}. Changing it can break Windows or "
                                                  f"another person's files."))
                approved = self.confirmer.confirm(req2, token)
                if token.is_cancelled:
                    return _fail(tid, ErrorCode.CANCELLED, "cancelled while awaiting confirmation",
                                 decision=decision.decision)
                if not approved:
                    return _fail(tid, ErrorCode.CONFIRMATION_REQUIRED, "user did not confirm the protected location",
                                 decision=decision.decision)

        attempts = 0
        while True:
            attempts += 1
            res = self._run_once(tool, args, token)
            res.attempts, res.decision = attempts, decision.decision
            if (res.ok or res.error_code not in _RETRYABLE or spec.idempotency is not Idempotency.IDEMPOTENT
                    or attempts > spec.max_retries or token.is_cancelled):
                return res
            res.notes.append(f"attempt {attempts} failed with {res.error_code}; retrying")

    def _run_once(self, tool, args: BaseModel, token: CancelToken) -> ToolResult:
        spec = tool.spec
        ctx = ToolContext(token=token, workspace=self.workspace, deadline=time.monotonic() + spec.timeout_s)
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["out"] = tool.run(args, ctx)
            except BaseException as e:  # noqa: BLE001 - reported as a structured result
                box["err"] = e

        th = threading.Thread(target=target, name=f"tool-{spec.id}", daemon=True)
        th.start()
        uncertain = spec.side_effect is not SideEffect.READ_ONLY
        cancel_seen_at: float | None = None
        while th.is_alive():
            th.join(_POLL_S)
            now = time.monotonic()
            if token.is_cancelled and cancel_seen_at is None:
                cancel_seen_at = now
            if cancel_seen_at is not None and now - cancel_seen_at > CANCEL_GRACE_S and th.is_alive():
                return _fail(spec.id, ErrorCode.CANCELLED,
                             "cancelled; tool did not stop within grace period, outcome unknown",
                             uncertain=uncertain)
            if now > ctx.deadline and th.is_alive():
                return _fail(spec.id, ErrorCode.TIMEOUT, f"no result within {spec.timeout_s}s; outcome unknown",
                             uncertain=uncertain)

        if "err" in box:
            e = box["err"]
            if isinstance(e, ToolError):
                r = _fail(spec.id, e.code, e.message)
                r.output = {"details": redact(e.details)} if e.details else None
                return r
            return _fail(spec.id, ErrorCode.UNKNOWN, f"{type(e).__name__}: {e}", uncertain=uncertain)

        out = box.get("out")
        if not isinstance(out, spec.output_model):
            return _fail(spec.id, ErrorCode.UNKNOWN,
                         f"tool returned {type(out).__name__}, expected {spec.output_model.__name__}",
                         uncertain=uncertain)
        res = ToolResult(tool_id=spec.id, ok=True, output=out.model_dump(mode="json"), notes=ctx.notes)
        if cancel_seen_at is not None:
            res.notes.append("completed before cancellation took effect")
        return res


def _fail(tool_id: str, code: ErrorCode, message: str, *, uncertain: bool = False,
          decision: Decision | None = None) -> ToolResult:
    return ToolResult(tool_id=tool_id, ok=False, error_code=code, error_message=redact(message),
                      side_effect_uncertain=uncertain, decision=decision)


def _summarize(e: ValidationError) -> str:
    parts = []
    for err in e.errors()[:5]:
        loc = ".".join(str(x) for x in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
