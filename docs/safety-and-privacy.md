# Safety and Privacy (v2, Stage 2)

## What ORION can do at Stage 2
- Read, list, create (never overwrite), copy and delete-to-trash files **inside `workspace/` only**.
- Open Notepad, Calculator or Paint (no arguments).
- Nothing else: no shell, no browser, no network, no UI clicking or typing yet. It does not interpret goals; you pick a tool.

## Controls in place
| Control | Behaviour | Evidence |
|---|---|---|
| Kill switch | Button and global hotkey; cancels all tasks, closes an open confirmation dialog, blocks new tasks until reset; says "stopping N task(s)" while an action finishes | `tests/safety/test_kill_switch_and_dry_run.py`, `tests/integration/test_tool_console.py` |
| Dry-run default | On by default; the dry-run executor cannot call actions; it shows what policy *would* decide | same files |
| Tool allowlist | Only registered tools; no generic command tool | `tests/safety/test_policy_and_runtime.py` |
| Least privilege | `files.delete` not granted by default | `tests/unit/test_config.py` |
| Confirmation | Consequential actions always ask; default button is **No**; one approval covers one call | `test_tool_console.py`, `test_policy_and_runtime.py` |
| No relabelling | Policy reads the registered spec; a call cannot carry its own side-effect label; specs are immutable | `test_policy_and_runtime.py` |
| Workspace confinement | Traversal, absolute/UNC/drive paths, ADS, device names and junction escapes are rejected | `tests/safety/test_file_tools.py` (incl. a real junction) |
| No overwrite | write/copy use exclusive create | `test_file_tools.py` |
| Honest outcomes | Timeouts and cancels of non-read-only tools are marked **uncertain** (needs review), never success | `test_policy_and_runtime.py` |
| Strict config | Unknown keys, bad types and misspelt permissions are errors | `test_config.py` |
| Redaction | Secret-looking keys and token shapes are redacted in logs, DB errors and events | `tests/safety/test_log_redaction.py` |

## What is logged
Task titles, tool ids and arguments (redacted), statuses, evidence strings (file paths, sizes, hash prefixes, window titles), errors, kill-switch use. Stored in `<data_dir>/logs/orion.jsonl` and `<data_dir>/orion.db` (gitignored). File contents read by `files.read` are not logged (evidence has only size and hash). **However**, the step name shows the tool arguments (redacted, cut to 80 characters), so the first part of the text given to `files.write_new` does appear in the log and DB.

## What is never captured
No screenshots, keystrokes, clipboard, microphone or webcam: none of these exist yet.

## Known gaps (honest)
- Redaction is pattern-based; a bare secret in free text is not caught. Do not type secrets into ORION.
- A tool that ignores cancellation keeps running in the background after ORION stops waiting (Python cannot kill threads). All current tools check the token before making changes, but the residual risk is real for future long-running tools.
- `app.launch notepad` can report `verification_failed` when Notepad opens as a tab (see the tools reference).
- Delete has no undo command; files are recoverable from `workspace/.orion_trash/` by hand.
