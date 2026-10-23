"""Adapt a registered tool call into a runner Action."""

from __future__ import annotations

import json

from orion.execution.executor import Action, ActionError
from orion.execution.runtime import ToolCall, ToolRuntime
from orion.observability.logging import redact
from orion.orchestration.cancel import Cancelled, CancelToken
from orion.tools.errors import BLOCKING_CODES, ErrorCode


def tool_action(runtime: ToolRuntime, call: ToolCall) -> Action:
    def fn(token: CancelToken) -> str:
        r = runtime.execute(call, token)
        if r.ok:
            return r.evidence + (f" [{'; '.join(r.notes)}]" if r.notes else "")
        msg = f"{r.error_code}: {r.error_message}"
        if r.error_code is ErrorCode.CANCELLED and not r.side_effect_uncertain:
            raise Cancelled(msg)
        if r.side_effect_uncertain:
            msg += " [side effect uncertain: check before retrying]"
        raise ActionError(msg, blocked=r.error_code in BLOCKING_CODES, uncertain=r.side_effect_uncertain)

    args = json.dumps(redact(call.args), ensure_ascii=False)
    if len(args) > 80:
        args = args[:77] + "..."
    return Action(name=f"{call.tool_id} {args}", fn=fn, simulated=False, preview=lambda: runtime.preview(call))
