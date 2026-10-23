# ORION Architecture (v1, Stage 1)

Status labels: **implemented** = code exists and tests pass; **planned** = designed, not built.

## Implemented in Stage 1

```
PySide6 MainWindow (UI thread)
  ├─ task input, dry-run toggle (default ON), STOP ALL button, global hotkey
  ├─ task table + live log pane  ◀── queued Qt signal ──┐
  └─ start_task() ─▶ worker thread: TaskRunner.run()    │
                         ├─ CancelToken (from KillSwitch)│
                         ├─ Executor: RealExecutor | DryRunExecutor
                         ├─ TaskStore (SQLite) ──────────┤ events
                         └─ logging "orion.*" ─▶ JSONL (redacted)
```

| Module | Role |
|---|---|
| `orion.config` | Strict TOML config (`extra="forbid"`; BOM tolerated). Defaults are safe: dry-run on. |
| `orion.observability` | JSON-lines formatter; redaction of secret-looking keys and token shapes in msg, event and traceback. |
| `orion.orchestration.states` | Task/step statuses and the allowed-transition table; terminal states are final. |
| `orion.memory` | SQLite `tasks`, `steps`, `events`, `meta(schema_version)`; transitions validated inside a transaction. |
| `orion.orchestration.cancel` | `CancelToken`; latching `KillSwitch` (cancels all tokens, blocks new tasks until reset). |
| `orion.execution` | `Action` (Stage 1: a callable), `RealExecutor`, `DryRunExecutor` (has no code path that calls the action). |
| `orion.orchestration.runner` | Sequential runner: checks the token before each action, persists every transition, emits events. |
| `orion.app` | Main window, Win32 `RegisterHotKey` kill hotkey, entry point `python -m orion`. |

### Key behaviours
- **Kill switch:** STOP button or global hotkey (default `Ctrl+Alt+End`). It cancels every running task; the runner never starts another action after the token is cancelled; long actions wait on the token, so they wake early. The switch latches until "Reset kill switch" is pressed, and reset is refused while tasks are still stopping.
- **Dry-run:** steps go `pending → ready → skipped` with evidence `dry-run: … not executed`; the task ends `skipped`, never `succeeded`.
- **Honest results:** simulated evidence is prefixed `simulated:`. Failures carry the exception type and message (redacted).

## Planned (later stages), mapped onto these seams
| Stage | Plugs in where |
|---|---|
| 2: tool registry and policy | `Action.fn` is replaced by a registered tool call; a policy check sits between runner and executor |
| 3: planner and task graph | the runner's list of actions becomes a validated dependency graph with checkpoints and resume |
| 4: perception and verification | after each action: re-observe, then verifier postconditions decide `succeeded` |
| 5: recovery | runner failure branch hands off to the recovery engine instead of stopping |
