# ORION Architecture (v2, Stage 2)

Status labels: **implemented** = code exists and tests pass; **planned** = designed, not built.

## Implemented (Stages 1 and 2)

```
PySide6 MainWindow (UI thread)
  ├─ tool console (tool + JSON args), simulated-task input, dry-run toggle (default ON)
  ├─ STOP ALL button + global hotkey → KillSwitch
  ├─ QtConfirmer: confirmation dialog, closed by the kill switch
  ├─ task table + live log pane  ◀── queued Qt signal ───────────┐
  └─ worker thread: TaskRunner.run()                              │
        ├─ CancelToken (from KillSwitch)                          │ events
        ├─ Executor: RealExecutor | DryRunExecutor (never calls)  │
        │     └─ Action ── tool_action ─▶ ToolRuntime             │
        │                    ├─ ToolRegistry (allowlist)          │
        │                    ├─ PolicyEngine (spec-based)         │
        │                    ├─ Confirmer (one call only)         │
        │                    └─ tool thread with timeout/cancel   │
        ├─ TaskStore (SQLite) ────────────────────────────────────┘
        └─ logging "orion.*" ─▶ JSONL (redacted)
```

| Module | Role |
|---|---|
| `orion.config` | Strict TOML config: workspace, granted permissions, confirm_reversible, dry-run default. |
| `orion.observability` | JSON-lines logs; redaction of secret-looking keys and token shapes. |
| `orion.orchestration.states` | Statuses incl. `blocked` and `needs_review`; validated transitions. |
| `orion.memory` | SQLite tasks/steps/events; transitions inside transactions. |
| `orion.orchestration.cancel` | CancelToken; latching KillSwitch. |
| `orion.orchestration.runner` | Sequential runner; blocked vs failed vs needs_review vs cancelled. |
| `orion.execution` | Executors, `tool_action` adapter, `ToolRuntime` (validate → authorize → confirm → run → check output). |
| `orion.tools` | Tool contract (spec 8.1), error taxonomy (8.4), registry, file tools, `app.launch`, read-only Win32 helpers. |
| `orion.policy` | Allow / confirm / deny from the registered spec and granted permissions. |
| `orion.app` | Main window, tool console, confirmation dialog, hotkey. |

See `docs/tools-and-permissions.md` for the tool table.

### Threads, not asyncio (deliberate, for now)
Qt plus blocking Win32/UIA calls fit worker threads. Python cannot kill a thread, so the runtime stops *waiting* after the timeout or cancel grace period (0.5 s) and reports the outcome as uncertain for non-read-only tools. Revisit when async Playwright arrives in Stage 4.

## Planned, mapped onto these seams
| Stage | Plugs in where |
|---|---|
| 3: goals, task graph, planner, resume | the runner's list of actions becomes a validated dependency graph with checkpoints; task outcome adds "partially complete" and "unverified" (spec 9); history inspect/delete controls (spec 10) |
| 4: UIA and browser perception, verification | new tools behind the same runtime; re-observe after each action; verifier postconditions decide success |
| 5: recovery | the runner's failure branch hands off to the recovery engine |
| 6: visual grounding | perception fallback tier: fine-tuned SigLIP/CLIP scorer over hybrid candidates with conformal abstention; abstain → ask the user |
