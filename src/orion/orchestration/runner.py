"""Sequential task runner (Stage 1).

Runs a list of actions under one cancel token, persisting every status change
and emitting events for the UI. It is synchronous; the app calls it from a
worker thread. Planning, policy and verification plug in at later stages.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Sequence

from orion.execution.executor import Action, Executor
from orion.memory.store import TaskStore
from orion.orchestration.cancel import CancelToken, KillSwitch
from orion.orchestration.states import Status

log = logging.getLogger("orion.runner")

EventSink = Callable[[dict[str, Any]], None]


def simulated_action(name: str, seconds: float) -> Action:
    """A harmless action that only waits, waking early if cancelled."""

    def fn(token: CancelToken) -> str:
        if token.wait(seconds):
            token.raise_if_cancelled()
        return f"waited {seconds:.2f}s"

    return Action(name=name, fn=fn, simulated=True)


class TaskRunner:
    def __init__(self, store: TaskStore, kill_switch: KillSwitch, on_event: EventSink | None = None):
        self.store = store
        self.kill_switch = kill_switch
        self.on_event = on_event or (lambda e: None)
        # monotonic start time of every action actually handed to an executor (for tests/metrics)
        self.action_starts: list[float] = []

    def _emit(self, task_id: int, level: str, kind: str, message: str, **data: Any) -> None:
        self.store.add_event(task_id, level, kind, message, data or None)
        log.log(logging.getLevelName(level), message, extra={"event": {"task_id": task_id, "kind": kind, **data}})
        self.on_event({"task_id": task_id, "level": level, "kind": kind, "message": message, **data})

    def create(self, title: str, actions: Sequence[Action], dry_run: bool) -> int:
        task_id = self.store.create_task(title, dry_run)
        for i, a in enumerate(actions):
            self.store.add_step(task_id, i, a.name)
        mode = "dry-run" if dry_run else "live"
        self._emit(task_id, "INFO", "task_created", f"task {task_id} created ({mode}, {len(actions)} steps)")
        return task_id

    def run(self, task_id: int, actions: Sequence[Action], executor: Executor, token: CancelToken) -> Status:
        steps = self.store.list_steps(task_id)
        self.store.set_task_status(task_id, Status.READY)
        self.store.set_task_status(task_id, Status.RUNNING)
        self._emit(task_id, "INFO", "task_running", f"task {task_id} running")
        final = Status.SKIPPED if executor.dry_run else Status.SUCCEEDED
        error: str | None = None
        try:
            for step, action in zip(steps, actions):
                sid = step["id"]
                if token.is_cancelled:
                    final = Status.CANCELLED
                    break
                self.store.set_step_status(sid, Status.READY)
                if executor.dry_run:
                    res = executor.execute(action, token)
                    self.store.set_step_status(sid, Status.SKIPPED, res.evidence)
                    self._emit(task_id, "INFO", "step_planned", res.evidence, step=step["idx"])
                    continue
                self.store.set_step_status(sid, Status.RUNNING)
                self._emit(task_id, "INFO", "step_started", f"step {step['idx']}: {action.name}", step=step["idx"])
                self.action_starts.append(time.monotonic())
                res = executor.execute(action, token)
                if res.cancelled:
                    self.store.set_step_status(sid, Status.CANCELLED, res.evidence)
                    final = Status.CANCELLED
                    break
                if not res.ok:
                    self.store.set_step_status(sid, Status.FAILED, res.evidence)
                    self._emit(task_id, "ERROR", "step_failed", f"step {step['idx']} failed: {res.evidence}",
                               step=step["idx"])
                    final, error = Status.FAILED, res.evidence
                    break
                self.store.set_step_status(sid, Status.SUCCEEDED, res.evidence)
                self._emit(task_id, "INFO", "step_done", f"step {step['idx']}: {res.evidence}", step=step["idx"])
        except Exception as e:  # noqa: BLE001 - runner bugs must still end the task visibly
            final, error = Status.FAILED, f"runner error: {type(e).__name__}: {e}"
            log.exception("runner error", extra={"event": {"task_id": task_id}})
        finally:
            self.kill_switch.release(token)

        # Close out steps that never ran.
        for step in self.store.list_steps(task_id):
            if step["status"] in (Status.PENDING, Status.READY):
                self.store.set_step_status(step["id"], Status.CANCELLED if final == Status.CANCELLED
                                           else Status.SKIPPED)

        self.store.set_task_status(task_id, final, error)
        if final == Status.CANCELLED:
            latency = (time.monotonic() - token.cancelled_at) if token.cancelled_at else None
            self._emit(task_id, "WARNING", "task_cancelled",
                       f"task {task_id} cancelled ({token.reason}); stopped "
                       f"{latency * 1000:.0f} ms after the stop request" if latency is not None
                       else f"task {task_id} cancelled",
                       stop_latency_s=latency)
        elif final == Status.FAILED:
            self._emit(task_id, "ERROR", "task_failed", f"task {task_id} failed: {error}")
        elif final == Status.SKIPPED:
            self._emit(task_id, "INFO", "task_dry_run_done",
                       f"task {task_id}: dry run complete, {len(actions)} actions planned, 0 executed")
        else:
            self._emit(task_id, "INFO", "task_succeeded",
                       f"task {task_id} finished: all {len(actions)} simulated steps completed")
        return final
