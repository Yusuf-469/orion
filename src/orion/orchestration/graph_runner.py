"""Plan (task graph) runner with checkpoints, verification and safe resume.

Loop per eligible step: resolve references → checkpoint if consequential →
record action id + RUNNING (one transaction) → execute through the tool
runtime (policy, confirmation, timeout) → verify postconditions by observing
the environment → persist. At the end, goal completion checks decide the
task outcome (spec 9); a step's own report is never enough.

Resume rule (spec 10, gate S6): a step found RUNNING after a crash is
  - read-only: re-run;
  - otherwise: re-observe its postconditions; if they hold → succeeded
    ("verified after resume"); if not → needs_review, never repeated blindly.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

from orion.execution.runtime import ToolCall, ToolRuntime
from orion.memory.store import TaskStore
from orion.orchestration.cancel import CancelToken, KillSwitch
from orion.orchestration.states import TERMINAL, Status
from orion.planner.schemas import Goal, Outcome, Plan, PlanStep, parse_ref
from orion.tools.base import SideEffect
from orion.tools.errors import BLOCKING_CODES, ErrorCode
from orion.verification import Verifier

log = logging.getLogger("orion.graph")

_PRIORITY = {SideEffect.READ_ONLY: 0, SideEffect.REVERSIBLE: 1, SideEffect.CONSEQUENTIAL: 2}
_TASK_STATUS = {
    Outcome.VERIFIED_COMPLETE: Status.SUCCEEDED,
    Outcome.UNVERIFIED: Status.NEEDS_REVIEW,
    Outcome.PARTIALLY_COMPLETE: Status.FAILED,
    Outcome.FAILED: Status.FAILED,
    Outcome.BLOCKED: Status.BLOCKED,
    Outcome.CANCELLED: Status.CANCELLED,
    Outcome.DRY_RUN: Status.SKIPPED,
}
_BAD_DEP = {Status.FAILED, Status.BLOCKED, Status.NEEDS_REVIEW, Status.CANCELLED, Status.SKIPPED}


class GraphRunner:
    def __init__(self, store: TaskStore, kill_switch: KillSwitch, runtime: ToolRuntime, verifier: Verifier,
                 on_event: Callable[[dict[str, Any]], None] | None = None):
        self.store = store
        self.kill_switch = kill_switch
        self.runtime = runtime
        self.verifier = verifier
        self.on_event = on_event or (lambda e: None)
        self.executed: list[tuple[int, str, str]] = []   # (task_id, step_key, action_id) for tests/metrics

    def _emit(self, task_id: int, level: str, kind: str, message: str, **data: Any) -> None:
        self.store.add_event(task_id, level, kind, message, data or None)
        log.log(logging.getLevelName(level), message, extra={"event": {"task_id": task_id, "kind": kind, **data}})
        self.on_event({"task_id": task_id, "level": level, "kind": kind, "message": message, **data})

    # --- creation --------------------------------------------------------------

    def create(self, goal: Goal, plan: Plan, planner: str, dry_run: bool) -> int:
        task_id = self.store.create_task(goal.objective, dry_run)
        self.store.save_plan(task_id, planner, goal.model_dump_json(), plan.model_dump_json())
        for i, s in enumerate(plan.steps):
            self.store.add_plan_step(task_id, i, s.id, s.description, s.tool_id, s.args)
        lines = "; ".join(f"{s.id}: {s.tool_id}" + (f" after {','.join(s.depends_on)}" if s.depends_on else "")
                          for s in plan.steps)
        self._emit(task_id, "INFO", "plan_created",
                   f"task {task_id} planned by {planner} ({'dry-run' if dry_run else 'live'}): {lines}")
        return task_id

    def _load(self, task_id: int) -> tuple[Goal, Plan]:
        row = self.store.load_plan(task_id)
        if row is None:
            raise KeyError(f"task {task_id} has no plan")
        return Goal.model_validate_json(row["goal_json"]), Plan.model_validate_json(row["plan_json"])

    # --- run / resume -----------------------------------------------------------

    def run(self, task_id: int, token: CancelToken, dry_run: bool) -> Outcome:
        self.store.set_task_status(task_id, Status.READY)
        self.store.set_task_status(task_id, Status.RUNNING)
        self._emit(task_id, "INFO", "task_running", f"task {task_id} running")
        return self._loop(task_id, token, dry_run)

    def resume(self, task_id: int, token: CancelToken) -> Outcome:
        task = self.store.get_task(task_id)
        if task["status"] not in (Status.READY, Status.RUNNING):
            raise ValueError(f"task {task_id} is {task['status']}, not interrupted")
        if task["status"] == Status.READY:
            self.store.set_task_status(task_id, Status.RUNNING)
        _, plan = self._load(task_id)
        by_key = {s.id: s for s in plan.steps}
        self._emit(task_id, "WARNING", "task_resuming", f"task {task_id} resuming after interruption; re-observing")
        for row in self.store.list_steps(task_id):
            step = by_key[row["step_key"]]
            spec = self.runtime.registry.get(step.tool_id).spec
            if row["status"] == Status.SUCCEEDED and step.postconditions:
                ok, res = self.verifier.check_all(step.postconditions)
                if not ok:
                    self._emit(task_id, "WARNING", "environment_changed",
                               f"step {step.id} succeeded earlier but its postconditions no longer hold: "
                               f"{'; '.join(r.evidence for r in res)}")
            if row["status"] != Status.RUNNING:
                continue
            if spec.side_effect is SideEffect.READ_ONLY:
                self.store.set_step_status(row["id"], Status.READY, "interrupted read-only step; will re-run")
                self._emit(task_id, "INFO", "resume_rerun", f"step {step.id} was interrupted; read-only, re-running")
                continue
            ok, res = self.verifier.check_all(step.postconditions) if step.postconditions else (False, [])
            if ok:
                ev = "verified after resume: " + "; ".join(r.evidence for r in res)
                self.store.set_step_status(row["id"], Status.SUCCEEDED, ev)
                self._emit(task_id, "INFO", "resume_verified", f"step {step.id} {ev}")
            else:
                why = "; ".join(r.evidence for r in res) or "no postconditions to check"
                ev = (f"interrupted during a {spec.side_effect} action (action {row['action_id']}); "
                      f"outcome unknown ({why}); NOT repeated")
                self.store.set_step_status(row["id"], Status.NEEDS_REVIEW, ev)
                self._emit(task_id, "ERROR", "resume_needs_review", f"step {step.id}: {ev}")
        return self._loop(task_id, token, dry_run=bool(task["dry_run"]))

    def _loop(self, task_id: int, token: CancelToken, dry_run: bool) -> Outcome:
        goal, plan = self._load(task_id)
        by_key = {s.id: s for s in plan.steps}
        order = {s.id: i for i, s in enumerate(plan.steps)}
        cancelled = False
        try:
            while True:
                rows = {r["step_key"]: r for r in self.store.list_steps(task_id)}
                if token.is_cancelled:
                    cancelled = True
                    break
                # In dry-run every step is "skipped (planned)", and that must not block its dependents.
                done = {Status.SUCCEEDED, Status.SKIPPED} if dry_run else {Status.SUCCEEDED}
                if not dry_run:
                    self._skip_unreachable(task_id, plan, rows)
                    rows = {r["step_key"]: r for r in self.store.list_steps(task_id)}
                eligible = [s for s in plan.steps if rows[s.id]["status"] in (Status.PENDING, Status.READY)
                            and all(rows[d]["status"] in done for d in s.depends_on)]
                if not eligible:
                    break
                step = min(eligible, key=lambda s: (
                    _PRIORITY[self.runtime.registry.get(s.tool_id).spec.side_effect], order[s.id]))
                stop = self._run_step(task_id, step, rows, by_key, token, dry_run)
                if stop:
                    cancelled = True
                    break
        except Exception as e:  # noqa: BLE001 - a runner bug must still end visibly
            log.exception("graph runner error", extra={"event": {"task_id": task_id}})
            self._emit(task_id, "ERROR", "runner_error", f"runner error: {type(e).__name__}: {e}")
        finally:
            self.kill_switch.release(token)
        return self._finish(task_id, goal, cancelled or token.is_cancelled, dry_run)

    def _skip_unreachable(self, task_id: int, plan: Plan, rows: dict) -> None:
        changed = True
        while changed:
            changed = False
            for s in plan.steps:
                r = rows[s.id]
                if r["status"] == Status.PENDING and any(rows[d]["status"] in _BAD_DEP for d in s.depends_on):
                    bad = [d for d in s.depends_on if rows[d]["status"] in _BAD_DEP]
                    self.store.set_step_status(r["id"], Status.SKIPPED, f"skipped: dependency {bad} did not succeed")
                    r["status"] = Status.SKIPPED
                    changed = True

    def _resolve_args(self, step: PlanStep, rows: dict) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in step.args.items():
            ref = parse_ref(v)
            if ref is None:
                out[k] = v
                continue
            src, field = ref
            data = json.loads(rows[src]["output_json"] or "null")
            if not isinstance(data, dict) or field not in data:
                raise LookupError(f"output {src}.{field} is not available")
            out[k] = data[field]
        return out

    def _run_step(self, task_id: int, step: PlanStep, rows: dict, by_key, token: CancelToken,
                  dry_run: bool) -> bool:
        """Run one step. Returns True if the task must stop (cancelled)."""
        row = rows[step.id]
        sid = row["id"]
        spec = self.runtime.registry.get(step.tool_id).spec
        if row["status"] == Status.PENDING:
            self.store.set_step_status(sid, Status.READY)

        if dry_run:
            preview = self.runtime.preview(ToolCall(tool_id=step.tool_id, args=step.args))
            self.store.set_step_status(sid, Status.SKIPPED, f"dry-run: not executed; {preview}")
            self._emit(task_id, "INFO", "step_planned", f"{step.id} {step.tool_id}: {preview}")
            return False

        try:
            args = self._resolve_args(step, rows)
        except LookupError as e:
            self.store.set_step_status(sid, Status.SKIPPED, f"skipped: {e}")
            self._emit(task_id, "ERROR", "step_failed", f"{step.id}: {e}")
            return False

        if step.checkpoint_before:
            self.store.save_checkpoint(task_id, f"before {step.id} ({step.tool_id})")
            self._emit(task_id, "INFO", "checkpoint", f"checkpoint saved before {step.id} ({spec.side_effect})")

        action_id = uuid.uuid4().hex
        self.store.mark_step_started(sid, action_id)
        self.executed.append((task_id, step.id, action_id))
        self._emit(task_id, "INFO", "step_started", f"{step.id}: {step.description} [{step.tool_id}]")
        r = self.runtime.execute(ToolCall(tool_id=step.tool_id, args=args), token)
        self.store.set_step_output(sid, r.output)

        if r.ok:
            ok, res = self.verifier.check_all(step.postconditions)
            ev = r.evidence + ("" if not res else " | verified: " + "; ".join(x.evidence for x in res))
            if ok:
                self.store.set_step_status(sid, Status.SUCCEEDED, ev)
                self._emit(task_id, "INFO", "step_done", f"{step.id}: {ev}")
            else:
                self.store.set_step_status(sid, Status.FAILED, f"{ErrorCode.VERIFICATION_FAILED}: {ev}")
                self._emit(task_id, "ERROR", "step_failed", f"{step.id} postconditions failed: {ev}")
            return False

        msg = r.evidence
        if r.error_code is ErrorCode.CANCELLED and not r.side_effect_uncertain:
            self.store.set_step_status(sid, Status.CANCELLED, msg)
            return True
        if r.side_effect_uncertain:
            self.store.set_step_status(sid, Status.NEEDS_REVIEW, msg + " [side effect uncertain]")
            self._emit(task_id, "ERROR", "step_failed", f"{step.id} outcome uncertain, needs review: {msg}")
            return r.error_code is ErrorCode.CANCELLED
        if r.error_code in BLOCKING_CODES:
            self.store.set_step_status(sid, Status.BLOCKED, msg)
            self._emit(task_id, "WARNING", "step_blocked", f"{step.id} blocked: {msg}")
            return False
        self.store.set_step_status(sid, Status.FAILED, msg)
        self._emit(task_id, "ERROR", "step_failed", f"{step.id} failed: {msg}")
        return False

    # --- outcome ----------------------------------------------------------------

    def _finish(self, task_id: int, goal: Goal, cancelled: bool, dry_run: bool) -> Outcome:
        for r in self.store.list_steps(task_id):
            if r["status"] in (Status.PENDING, Status.READY):
                self.store.set_step_status(r["id"], Status.CANCELLED if cancelled else Status.SKIPPED,
                                           "not run: task cancelled" if cancelled else "not run")
        steps = self.store.list_steps(task_id)
        statuses = [Status(s["status"]) for s in steps]
        all_ok = all(s == Status.SUCCEEDED for s in statuses)
        checks_ok, results = self.verifier.check_all(goal.completion_checks)
        n_pass = sum(r.ok for r in results)

        if cancelled:
            outcome = Outcome.CANCELLED
        elif dry_run:
            outcome = Outcome.DRY_RUN
        elif goal.completion_checks and checks_ok:
            outcome = Outcome.VERIFIED_COMPLETE
        elif not goal.completion_checks and all_ok:
            outcome = Outcome.UNVERIFIED
        elif n_pass > 0 or any(s == Status.SUCCEEDED for s in statuses):
            outcome = Outcome.PARTIALLY_COMPLETE
        elif any(s == Status.BLOCKED for s in statuses):
            outcome = Outcome.BLOCKED
        else:
            outcome = Outcome.FAILED

        if outcome is Outcome.PARTIALLY_COMPLETE and all(
                s in (Status.SUCCEEDED, Status.BLOCKED, Status.SKIPPED) for s in statuses) and not n_pass:
            outcome = Outcome.BLOCKED

        task = self.store.get_task(task_id)
        target = _TASK_STATUS[outcome]
        if task["status"] not in TERMINAL and task["status"] != target:
            self.store.set_task_status(task_id, target,
                                       None if outcome is Outcome.VERIFIED_COMPLETE else f"outcome: {outcome}")
        self.store.set_task_outcome(task_id, outcome)
        summary = "; ".join(r.evidence for r in results) if results else "no completion checks"
        level = "INFO" if outcome in (Outcome.VERIFIED_COMPLETE, Outcome.DRY_RUN) else "WARNING"
        self._emit(task_id, level, "task_outcome", f"task {task_id}: {outcome.value.upper()} ({summary})",
                   outcome=outcome.value)
        return outcome
