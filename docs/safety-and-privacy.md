# Safety and Privacy (v1, Stage 1)

## What ORION can do at Stage 1
Nothing outside itself. Every task runs a **simulated** job that only waits. No tool touches the desktop, browser, files or network. The only OS-level hook is the global kill hotkey (`RegisterHotKey`), which is released when the app closes.

## Controls in place
| Control | Behaviour | Evidence |
|---|---|---|
| Kill switch | Button and global hotkey; cancels all tasks; no new action starts afterwards; latches until reset | `tests/safety/test_kill_switch_and_dry_run.py`, `tests/integration/test_app_shell.py` |
| Dry-run default | On by default (`dry_run_default = true`); dry-run executor cannot call actions | same files |
| Strict config | Unknown keys and bad types are errors, so a typo cannot silently turn off dry-run | `tests/unit/test_config.py` |
| Redaction | Secret-looking keys and token shapes are replaced with `[REDACTED]` in logs, DB errors and events | `tests/safety/test_log_redaction.py` |

## What is logged
- Task titles you type, task and step statuses, timestamps, simulated evidence, error messages (redacted), kill-switch use and hotkey registration.
- Location: `<data_dir>/logs/orion.jsonl` and `<data_dir>/orion.db` (default `data/`, gitignored).

## What is never logged or captured
- No screenshots, keystrokes, clipboard, microphone or webcam: none of these exist in Stage 1.
- Secret-looking values are redacted before writing. **Limitation:** redaction is pattern-based. A secret typed in free text without a recognisable key or format (e.g. a bare password in a task title) will not be caught. Do not type secrets into ORION.

## Known gaps (honest)
- The hotkey test posts `WM_HOTKEY` to ORION's own window. Physically pressing the keys is a **manual** check (`docs/stage1_manual_checklist.md`).
- If another program already owns `Ctrl+Alt+End`, registration fails. ORION shows this in red and in the log; the STOP button still works. Change the key in `orion.toml`.
- Stop latency is measured for simulated actions only. Real tools (Stage 2+) must also honour the token; this is a design rule, not yet tested.
