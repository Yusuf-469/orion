"""Plan validation (spec 5.3): nothing from a planner runs until this passes.

Errors make a plan invalid. Warnings are shown but do not block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import get_args, get_origin
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import ValidationError

from orion.planner.schemas import (
    FileAbsent, FileContains, FileExists, FilesIdentical, Goal, NotepadShows, Plan, PlanStep, parse_ref,
)
from orion.policy.engine import Decision, PolicyEngine
from orion.tools.base import SideEffect
from orion.tools.errors import ToolError
from orion.tools.files.workspace import resolve_in_workspace
from orion.tools.registry import ToolRegistry

# Arguments that name something a non-read-only tool changes.
WRITE_ARGS = ("path", "dst")
_NEVER_DONE = [(r"\bsubmit|\bsend\b|\bpost\b", "submit, send or post anything"),
               (r"\bbuy\b|\bpurchase|\bpay\b", "buy or pay for anything")]
USER_ONLY_ARGS = frozenset({"user_choice"})   # filled in by recovery from the user's answer, never by a planner
_DUMMY = {str: "x", int: 0, float: 0.0, bool: False}


@dataclass(frozen=True)
class PlanIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    step_id: str | None = None

    def __str__(self) -> str:
        where = f"[{self.step_id}] " if self.step_id else ""
        return f"{self.severity}: {self.code}: {where}{self.message}"


def _dummy(ann):
    """A placeholder of the right shape for a referenced output, e.g. list[list[str]] -> [["x"]]."""
    if get_origin(ann) is list:
        inner = get_args(ann)
        item = _dummy(inner[0]) if inner else "x"
        return None if item is None else [item]
    return _DUMMY.get(ann)


def _norm(p: str) -> str:
    return PureWindowsPath(p).as_posix().strip("/").lower()


def _authorized(path: str, allowed: list[str]) -> bool:
    n = _norm(path)
    return any(n == _norm(a) or n.startswith(_norm(a) + "/") for a in allowed if _norm(a))


_REQ_PATH = re.compile(r'"([^"]+)"|\'([^\']+)\'|([^\s"\']*[\\/.][^\s"\']*\w)')


def request_paths(request: str) -> set[str]:
    """Path-like tokens the user actually typed (quoted strings, or tokens with a dot or slash)."""
    out = set()
    for m in _REQ_PATH.finditer(request):
        tok = next(g for g in m.groups() if g)
        if "." in tok or "/" in tok or "\\" in tok:
            out.add(_norm(tok))
    return out


def _check_paths(check) -> list[str]:
    if isinstance(check, (FileExists, FileAbsent, FileContains, NotepadShows)):
        return [check.path]
    if isinstance(check, FilesIdentical):
        return [check.a, check.b]
    return []


def topo_order(plan: Plan) -> list[str] | None:
    """Kahn's algorithm in plan order. None if there is a cycle."""
    ids = [s.id for s in plan.steps]
    indeg = {i: 0 for i in ids}
    children: dict[str, list[str]] = {i: [] for i in ids}
    for s in plan.steps:
        for d in s.depends_on:
            if d in indeg:
                indeg[s.id] += 1
                children[d].append(s.id)
    ready = [i for i in ids if indeg[i] == 0]
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for c in children[n]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    return order if len(order) == len(ids) else None


def ancestors(plan: Plan) -> dict[str, set[str]]:
    by_id = {s.id: s for s in plan.steps}
    memo: dict[str, set[str]] = {}

    def visit(i: str, stack: frozenset[str]) -> set[str]:
        if i in memo:
            return memo[i]
        out: set[str] = set()
        for d in by_id[i].depends_on:
            if d in by_id and d not in stack:
                out |= {d} | visit(d, stack | {d})
        memo[i] = out
        return out

    return {s.id: visit(s.id, frozenset({s.id})) for s in plan.steps}


def validate_plan(plan: Plan, goal: Goal, registry: ToolRegistry, policy: PolicyEngine,
                  workspace: Path) -> list[PlanIssue]:
    issues: list[PlanIssue] = []
    err = lambda code, msg, sid=None: issues.append(PlanIssue("error", code, msg, sid))  # noqa: E731
    warn = lambda code, msg, sid=None: issues.append(PlanIssue("warning", code, msg, sid))  # noqa: E731

    if plan.goal_id != goal.goal_id:
        err("goal_mismatch", f"plan is for goal {plan.goal_id}, not {goal.goal_id}")
    for q in goal.missing_info:
        err("missing_info", f"needs an answer first: {q}")

    ids = [s.id for s in plan.steps]
    dupes = {i for i in ids if ids.count(i) > 1}
    for d in sorted(dupes):
        err("duplicate_step", f"step id {d!r} used more than once", d)
    known = set(ids)
    for s in plan.steps:
        for d in s.depends_on:
            if d == s.id:
                err("self_dependency", "step depends on itself", s.id)
            elif d not in known:
                err("unknown_dependency", f"depends on missing step {d!r}", s.id)
    if not dupes and topo_order(plan) is None:
        err("cycle", "dependencies contain a cycle")
        return issues   # ancestor analysis below assumes a DAG
    anc = ancestors(plan) if not dupes else {s.id: set() for s in plan.steps}
    by_id = {s.id: s for s in plan.steps}

    for s in plan.steps:
        _validate_step(s, goal, registry, policy, workspace, anc, by_id, err, warn)

    _check_intent(plan, goal, registry, err, warn)

    for c in goal.completion_checks:
        _validate_check(c, workspace, None, err)
    if not goal.completion_checks:
        warn("no_completion_checks", "goal has no completion checks; success can only be 'unverified'")
    return issues


def _check_intent(plan: Plan, goal: Goal, registry: ToolRegistry, err, warn) -> None:
    """Intent drift: a plan may only change paths the user named (plus '<named>.bak' backups).

    Catches planners (e.g. an LLM) that invent destinations or silently rewrite a path the user
    typed. It cannot catch invented file *content*; LLM plans still need user review.
    """
    named = request_paths(goal.request)
    used: set[str] = set()
    for s in plan.steps:
        for k in ("path", "src", "dst", "page"):
            v = s.args.get(k)
            if isinstance(v, str) and parse_ref(v) is None:
                used.add(_norm(v))
        if s.tool_id not in registry or registry.get(s.tool_id).spec.side_effect is SideEffect.READ_ONLY:
            continue
        for k in WRITE_ARGS:
            v = s.args.get(k)
            if not isinstance(v, str) or parse_ref(v) is not None:
                continue
            n = _norm(v)
            if n not in named and not (n.endswith(".bak") and n[:-4] in named):
                err("intent_drift", f"plan changes {v!r}, which the request never mentions", s.id)
    for p in sorted(named - used):
        warn("intent_drift", f"the request mentions {p!r} but the plan never uses it")

    # Parts of a request ORION never does (it has no tool for them): say so instead of silently dropping them.
    for words, what in _NEVER_DONE:
        if re.search(words, goal.request, re.I) and not any(re.search(words, s.tool_id, re.I) for s in plan.steps):
            warn("will_not_do", f"ORION does not {what}; it will do the rest and stop before that")

    # Text a plan writes must come from the user's own words (seen with Phi-3.5: invented content).
    req = _squash(goal.request)
    for s in plan.steps:
        if s.tool_id == "browser.fill_form" and isinstance(s.args.get("fields"), dict):
            for name, val in s.args["fields"].items():
                if isinstance(val, str) and _squash(val) not in req:
                    err("intent_drift", f"form value for {name!r} does not come from the request", s.id)
        v = s.args.get("content", s.args.get("text"))
        if s.tool_id in ("files.write_new", "notepad.set_text") and isinstance(v, str) and parse_ref(v) is None:
            if not v.strip() and "empty" not in req:
                # '' is a substring of everything; an empty file must be asked for explicitly.
                err("intent_drift", "file content is empty but the request did not ask for an empty file", s.id)
            elif _squash(v) not in req:
                err("intent_drift", "file content does not come from the request (invented text)", s.id)


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def _validate_step(s: PlanStep, goal: Goal, registry, policy, workspace, anc, by_id, err, warn) -> None:
    if s.tool_id not in registry:
        err("unknown_tool", f"no registered tool {s.tool_id!r}", s.id)
        return
    spec = registry.get(s.tool_id).spec

    # References must point at an ancestor's real output field.
    probe: dict[str, Any] = {}
    for k, v in s.args.items():
        ref = parse_ref(v)
        if ref is None:
            probe[k] = v
            continue
        src_id, field = ref
        if src_id not in by_id:
            err("bad_reference", f"argument {k!r} refers to unknown step {src_id!r}", s.id)
            continue
        if src_id not in anc[s.id]:
            err("bad_reference", f"argument {k!r} uses {src_id!r}, which is not a dependency", s.id)
            continue
        src_tool = by_id[src_id].tool_id
        if src_tool not in registry:
            continue
        out_fields = registry.get(src_tool).spec.output_model.model_fields
        if field not in out_fields:
            err("bad_reference", f"{src_tool} has no output field {field!r}", s.id)
            continue
        dummy = _dummy(out_fields[field].annotation)
        if dummy is None:
            err("bad_reference", f"output field {field!r} cannot be passed between steps", s.id)
            continue
        if spec.side_effect is not SideEffect.READ_ONLY and k in WRITE_ARGS:
            err("unchecked_write_target", f"argument {k!r} of a changing step must be a literal path", s.id)
        probe[k] = dummy

    try:
        spec.input_model.model_validate(probe)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])
        err("invalid_args", msgs, s.id)

    d = policy.decide(spec)
    if d.decision is Decision.DENY:
        err("permission_denied", d.reason, s.id)

    if spec.side_effect is not SideEffect.READ_ONLY:
        for k in WRITE_ARGS:
            v = s.args.get(k)
            if isinstance(v, str) and parse_ref(v) is None:
                try:
                    resolve_in_workspace(workspace, v)
                except ToolError as e:
                    err("outside_workspace", e.message, s.id)
                    continue
                if not _authorized(v, goal.authorized_outputs):
                    err("unauthorized_output", f"{k}={v!r} is not in the goal's authorized outputs", s.id)

    for k in USER_ONLY_ARGS & set(s.args):
        err("user_only_argument", f"argument {k!r} can only come from the user's own answer, not a plan", s.id)

    c = goal.constraints
    if s.tool_id == "files.delete" and (c.preserve_source_files or not c.allow_delete):
        err("contradiction", "goal says source files must be preserved / deletion not allowed", s.id)
    if s.tool_id == "app.launch" and not c.allow_app_launch:
        err("contradiction", "goal does not allow launching apps", s.id)

    if spec.side_effect is SideEffect.CONSEQUENTIAL and not s.checkpoint_before:
        err("missing_checkpoint", "consequential step needs checkpoint_before=true", s.id)
    if spec.side_effect is SideEffect.REVERSIBLE:
        for a in anc[s.id]:
            a_tool = by_id[a].tool_id
            if a_tool in registry and registry.get(a_tool).spec.side_effect is SideEffect.CONSEQUENTIAL:
                warn("irreversible_first", f"depends on consequential step {a!r}; prefer reversible steps first",
                     s.id)

    for chk in s.postconditions:
        _validate_check(chk, workspace, s.id, err)
    if spec.side_effect is not SideEffect.READ_ONLY and not s.postconditions:
        warn("no_postconditions", "changing step has no postconditions; tool evidence only", s.id)


def _validate_check(check, workspace: Path, sid: str | None, err) -> None:
    for p in _check_paths(check):
        try:
            resolve_in_workspace(workspace, p)
        except ToolError as e:
            err("invalid_check", e.message, sid)
