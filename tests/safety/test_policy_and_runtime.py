"""Stage 2 gate: invalid arguments and denied permissions fail safely; cancellation is tested.

Uses fake tools that only count calls (mock).
"""

import dataclasses
import threading
import time
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from orion.execution.runtime import CANCEL_GRACE_S, ToolCall, ToolRuntime
from orion.orchestration.cancel import CancelToken
from orion.policy import Decision, DenyAllConfirmer, PolicyEngine
from orion.tools import (
    ErrorCode, Idempotency, Permission, SideEffect, Tool, ToolError, ToolRegistry, ToolSpec,
)

pytestmark = [pytest.mark.safety, pytest.mark.mock]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = 0


class Out(BaseModel):
    evidence: str


def make_tool(tool_id, side_effect, perms, fn, timeout=2.0, idem=Idempotency.IDEMPOTENT, retries=0):
    class T(Tool):
        spec = ToolSpec(id=tool_id, version="1", description="test", input_model=Args, output_model=Out,
                        permissions=frozenset(perms), side_effect=side_effect, timeout_s=timeout,
                        idempotency=idem, verification="test", max_retries=retries)

        def __init__(self):
            self.calls = 0

        def run(self, args, ctx):
            self.calls += 1
            return fn(self, args, ctx)

    return T()


ok = lambda self, a, c: Out(evidence=f"ran n={a.n}")  # noqa: E731


class Approve:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def confirm(self, req, token):
        self.asked.append(req)
        return self.answer


ALL = frozenset(Permission)


@pytest.fixture
def setup(tmp_path):
    def build(*tools, granted=ALL, confirmer=None):
        reg = ToolRegistry()
        for t in tools:
            reg.register(t)
        return ToolRuntime(reg, PolicyEngine(granted), confirmer or DenyAllConfirmer(), Path(tmp_path))
    return build


# --- registry ---------------------------------------------------------------

def test_registry_rejects_duplicates_and_bad_specs():
    reg = ToolRegistry()
    reg.register(make_tool("t.a", SideEffect.READ_ONLY, [], ok))
    with pytest.raises(ValueError):
        reg.register(make_tool("t.a", SideEffect.READ_ONLY, [], ok))
    with pytest.raises(ValueError):
        reg.register(make_tool("BadId", SideEffect.READ_ONLY, [], ok))
    with pytest.raises(ValueError):
        reg.register(make_tool("t.b", SideEffect.READ_ONLY, [], ok, timeout=0))


def test_unknown_tool_is_unsupported(setup):
    rt = setup()
    r = rt.execute(ToolCall(tool_id="shell.run", args={"cmd": "del *"}), CancelToken())
    assert not r.ok and r.error_code == ErrorCode.UNSUPPORTED_CAPABILITY


# --- invalid input ----------------------------------------------------------

@pytest.mark.parametrize("args", [{"n": "lots"}, {"n": 1, "extra": True}, {"n": [1]}])
def test_invalid_args_fail_before_running(setup, args):
    t = make_tool("t.read", SideEffect.READ_ONLY, [Permission.FILES_READ], ok)
    r = setup(t).execute(ToolCall(tool_id="t.read", args=args), CancelToken())
    assert r.error_code == ErrorCode.INVALID_INPUT and t.calls == 0


# --- permissions and confirmation ---------------------------------------------

def test_missing_permission_denied_without_running(setup):
    t = make_tool("t.write", SideEffect.REVERSIBLE, [Permission.FILES_WRITE], ok)
    rt = setup(t, granted=frozenset({Permission.FILES_READ}))
    r = rt.execute(ToolCall(tool_id="t.write"), CancelToken())
    assert r.error_code == ErrorCode.PERMISSION_DENIED and r.decision == Decision.DENY and t.calls == 0
    assert "files.write" in r.error_message


def test_consequential_needs_confirmation_and_decline_blocks(setup):
    t = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [Permission.FILES_DELETE], ok)
    r = setup(t).execute(ToolCall(tool_id="t.delete"), CancelToken())
    assert r.error_code == ErrorCode.CONFIRMATION_REQUIRED and t.calls == 0


def test_each_consequential_call_asks_again(setup):
    t = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [Permission.FILES_DELETE], ok)
    conf = Approve(True)
    rt = setup(t, confirmer=conf)
    assert rt.execute(ToolCall(tool_id="t.delete"), CancelToken()).ok
    assert rt.execute(ToolCall(tool_id="t.delete"), CancelToken()).ok
    assert len(conf.asked) == 2 and t.calls == 2


def test_policy_has_no_switch_to_skip_consequential_confirmation():
    spec = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [], ok).spec
    for confirm_reversible in (False, True):
        assert PolicyEngine(ALL, confirm_reversible).decide(spec).decision == Decision.CONFIRM


# --- relabel attempts ---------------------------------------------------------

def test_call_cannot_declare_its_own_side_effect():
    with pytest.raises(ValidationError):
        ToolCall(tool_id="t.delete", args={}, side_effect="read_only")


def test_side_effect_hidden_in_args_is_rejected(setup):
    t = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [Permission.FILES_DELETE], ok)
    r = setup(t, confirmer=Approve(True)).execute(
        ToolCall(tool_id="t.delete", args={"side_effect": "read_only"}), CancelToken())
    assert r.error_code == ErrorCode.INVALID_INPUT and t.calls == 0


def test_registered_spec_is_immutable():
    t = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [], ok)
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.spec.side_effect = SideEffect.READ_ONLY


# --- timeout -------------------------------------------------------------------

def test_timeout_reports_uncertain_side_effect(setup):
    t = make_tool("t.slow", SideEffect.REVERSIBLE, [], lambda s, a, c: (time.sleep(1.0), Out(evidence="x"))[1],
                  timeout=0.2)
    t0 = time.monotonic()
    r = setup(t).execute(ToolCall(tool_id="t.slow"), CancelToken())
    assert r.error_code == ErrorCode.TIMEOUT and r.side_effect_uncertain
    assert time.monotonic() - t0 < 0.6


def test_read_only_timeout_is_not_uncertain(setup):
    t = make_tool("t.slowread", SideEffect.READ_ONLY, [], lambda s, a, c: (time.sleep(1.0), Out(evidence="x"))[1],
                  timeout=0.2)
    r = setup(t).execute(ToolCall(tool_id="t.slowread"), CancelToken())
    assert r.error_code == ErrorCode.TIMEOUT and not r.side_effect_uncertain


# --- cancellation ----------------------------------------------------------------

def test_cancel_before_start_runs_nothing(setup):
    t = make_tool("t.read", SideEffect.READ_ONLY, [], ok)
    tok = CancelToken()
    tok.cancel("test")
    assert setup(t).execute(ToolCall(tool_id="t.read"), tok).error_code == ErrorCode.CANCELLED
    assert t.calls == 0


def test_cooperative_tool_cancels_fast(setup):
    def coop(self, a, ctx):
        if ctx.token.wait(5):
            raise ToolError(ErrorCode.CANCELLED, "stopped on request")
        return Out(evidence="x")

    t = make_tool("t.coop", SideEffect.REVERSIBLE, [], coop, timeout=10)
    tok = CancelToken()
    threading.Timer(0.1, tok.cancel, args=("test",)).start()
    t0 = time.monotonic()
    r = setup(t).execute(ToolCall(tool_id="t.coop"), tok)
    assert r.error_code == ErrorCode.CANCELLED and time.monotonic() - t0 < 0.4


def test_uncooperative_tool_cancel_reports_unknown_outcome(setup):
    t = make_tool("t.stubborn", SideEffect.REVERSIBLE, [], lambda s, a, c: (time.sleep(2), Out(evidence="x"))[1],
                  timeout=10)
    tok = CancelToken()
    threading.Timer(0.1, tok.cancel, args=("test",)).start()
    t0 = time.monotonic()
    r = setup(t).execute(ToolCall(tool_id="t.stubborn"), tok)
    assert r.error_code == ErrorCode.CANCELLED and r.side_effect_uncertain
    assert time.monotonic() - t0 < 0.1 + CANCEL_GRACE_S + 0.3


def test_cancel_during_confirmation(setup):
    t = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [Permission.FILES_DELETE], ok)

    class CancelWhileAsking:
        def confirm(self, req, token):
            token.cancel("kill switch")
            return True  # even an approval must not run after cancellation

    r = setup(t, confirmer=CancelWhileAsking()).execute(ToolCall(tool_id="t.delete"), CancelToken())
    assert r.error_code == ErrorCode.CANCELLED and t.calls == 0


# --- retries and contracts -----------------------------------------------------------

def _flaky(fail_times):
    def fn(self, a, c):
        if self.calls <= fail_times:
            raise ToolError(ErrorCode.APPLICATION_UNAVAILABLE, "not ready")
        return Out(evidence="ok")
    return fn


def test_idempotent_tool_retried_within_limit(setup):
    t = make_tool("t.flaky", SideEffect.READ_ONLY, [], _flaky(2), retries=2)
    r = setup(t).execute(ToolCall(tool_id="t.flaky"), CancelToken())
    assert r.ok and r.attempts == 3


def test_non_idempotent_tool_never_auto_retried(setup):
    t = make_tool("t.once", SideEffect.REVERSIBLE, [], _flaky(1), idem=Idempotency.NON_IDEMPOTENT, retries=5)
    r = setup(t).execute(ToolCall(tool_id="t.once"), CancelToken())
    assert not r.ok and r.attempts == 1 and t.calls == 1


def test_wrong_output_type_is_not_success(setup):
    t = make_tool("t.bad", SideEffect.READ_ONLY, [], lambda s, a, c: {"evidence": "looks fine"})
    r = setup(t).execute(ToolCall(tool_id="t.bad"), CancelToken())
    assert not r.ok and r.error_code == ErrorCode.UNKNOWN


def test_preview_executes_nothing(setup):
    t = make_tool("t.delete", SideEffect.CONSEQUENTIAL, [Permission.FILES_DELETE], ok)
    rt = setup(t)
    assert "would confirm" in rt.preview(ToolCall(tool_id="t.delete"))
    assert "invalid_input" in rt.preview(ToolCall(tool_id="t.delete", args={"n": "x"}))
    assert t.calls == 0
