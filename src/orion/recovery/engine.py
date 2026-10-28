"""Recovery engine (spec 9): classify a failed step and propose ONE safe fix, then the step is retried once.

Only failures where nothing was changed are recoverable here:
  - a dialog blocks ORION's Notepad window   -> ask the user, then close it like Cancel / X
  - ORION's Notepad tab is no longer active  -> bring it back with notepad.open_file
  - screen.click found several equally likely matches -> ask "did you mean A or B?", then retry the
    click restricted to the place the user picked (Recovery.retry_args)
Uncertain outcomes are never retried; everything else fails or blocks as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from orion.execution.runtime import ToolCall, ToolResult, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy.engine import ConfirmationRequest, Confirmer
from orion.tools.base import SideEffect
from orion.tools.errors import ErrorCode


@dataclass
class Recovery:
    kind: Literal["dismiss_dialog", "reacquire_tab", "ask_choice"]
    description: str
    data: dict[str, Any] = field(default_factory=dict)
    retry_args: dict[str, Any] | None = None    # set by apply() when the retry must use different args


class RecoveryEngine:
    def __init__(self, runtime: ToolRuntime, confirmer: Confirmer):
        self.runtime = runtime
        self.confirmer = confirmer

    def propose(self, tool_id: str, args: dict[str, Any], result: ToolResult) -> Recovery | None:
        if result.ok or result.side_effect_uncertain or result.error_code is ErrorCode.CANCELLED:
            return None
        d = (result.output or {}).get("details") or {}
        if result.error_code is ErrorCode.STALE_STATE and "dialog_hwnd" in d:
            title = d.get("blocked_by_dialog") or "untitled"
            return Recovery("dismiss_dialog", f"close the '{title}' dialog blocking Notepad (like Cancel)", d)
        if (result.error_code in (ErrorCode.STALE_STATE, ErrorCode.TARGET_NOT_FOUND) and "tab_not_active" in d
                and tool_id.startswith("notepad.") and isinstance(args.get("path"), str)):
            return Recovery("reacquire_tab", f"bring {d['tab_not_active']} back to the front in Notepad",
                            {"path": args["path"]})
        if (result.error_code is ErrorCode.TARGET_NOT_FOUND and tool_id == "screen.click"
                and len(d.get("choices") or []) >= 2 and args.get("user_choice") is None):
            return Recovery("ask_choice", f"ask you which '{args.get('target')}' you meant",
                            {"choices": d["choices"], "args": dict(args)})
        return None

    def apply(self, rec: Recovery, token: CancelToken) -> tuple[bool, str]:
        if token.is_cancelled:
            return False, "cancelled"
        if rec.kind == "dismiss_dialog":
            from orion.tools.windows.notepad import blocking_dialog, close_dialog
            title = rec.data.get("blocked_by_dialog") or "untitled"
            req = ConfirmationRequest(
                tool_id="recovery.dismiss_dialog", side_effect=SideEffect.REVERSIBLE,
                action=f"A '{title}' dialog appeared and is blocking Notepad. Close it?",
                consequence="ORION closes it like pressing Cancel or the X, then retries the step. "
                            "Nothing is saved, deleted or sent.")
            if not self.confirmer.confirm(req, token) or token.is_cancelled:
                return False, f"you chose not to close the '{title}' dialog"
            # Only close the dialog if it is still the one blocking ORION's window.
            current = blocking_dialog(rec.data["window_hwnd"])
            if current is None:
                return True, "the dialog had already closed"
            if current[0] != rec.data["dialog_hwnd"]:
                return False, "a different dialog is open now; not touching it"
            if not close_dialog(current[0]):
                return False, f"the '{title}' dialog did not close"
            return True, f"closed the '{title}' dialog"
        if rec.kind == "reacquire_tab":
            r = self.runtime.execute(ToolCall(tool_id="notepad.open_file", args={"path": rec.data["path"]}), token)
            return r.ok, r.evidence
        if rec.kind == "ask_choice":
            choose = getattr(self.confirmer, "choose", None)
            if choose is None:
                return False, "several matches and no way to ask you; not clicking"
            ch = rec.data["choices"]
            target = rec.data["args"].get("target")
            req = ConfirmationRequest(
                tool_id="screen.click", side_effect=SideEffect.REVERSIBLE,
                action=f"I see more than one '{target}'. Which one did you mean?",
                consequence="ORION clicks only the one you pick, and only if it still matches.")
            pick = choose(req, [f"'{c['text']}' at the {c['where']}" for c in ch], token)
            if pick is None or token.is_cancelled:
                return False, "you did not pick one; not clicking"
            c = ch[pick]
            rec.retry_args = {**rec.data["args"], "user_choice": list(c["at"])}
            return True, f"you picked '{c['text']}' at the {c['where']}"
        return False, f"unknown recovery {rec.kind}"
