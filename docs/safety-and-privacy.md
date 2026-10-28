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

## Local LLM (added 2026-10-27, research use only)
- Ollama 0.40.11 and Phi-3.5-mini (3.8B, Q4_0, **MIT licence, verified with `ollama show --license`**) are installed for the planner experiment (C4). The app itself still uses the deterministic template planner.
- The Ollama server listens on **127.0.0.1:11434** (verified). `OllamaBackend` refuses any non-loopback URL, so prompts (which contain the user's request and the tool list) never leave the machine.
- Model output is **untrusted**: it is parsed, schema-checked and run through the same plan validator, policy engine and confirmation flow as any plan. The model cannot change the user's request, the goal id, permissions or a tool's side-effect category (tested).
- The app can use the LLM planner only when `planner = "llm"` is set in `orion.toml`. Every LLM plan is shown in a review dialog (default **No**) before anything runs; plans that fail validation are never offered.
- Ollama's server (`ollama serve`) runs as a background process; the tray app's own server start failed on this machine on 2026-10-27, so the server was started directly. End it from Task Manager (`ollama.exe`), or uninstall with `winget uninstall Ollama.Ollama`. The model is stored under `%USERPROFILE%\.ollama\models` (about 2.2 GB).

## Seeing and clicking (added 2026-10-28)
- **Screenshots:** only of the one window ORION is working in (never the whole screen), kept in memory for OCR and never written to disk. OCR runs locally (RapidOCR, Apache-2.0, CPU).
- **screen.click** works only in allowlisted windows (currently only ORION's own canvas demo app). Adding an app needs a safety review.
- It abstains when no visible label matches well or when two places match almost equally; it never clicks the window frame's own Minimize/Maximize/Close; before a mouse click it checks that its window is really the one under that point, and it puts the cursor back afterwards.
- **"Which one did you mean?"** When several places match, ORION shows them (label and rough position) and clicks only the one you pick, and only if it still matches there. "Neither", Esc or STOP means nothing is clicked. The pick covers that one click; a plan can never set it (the validator rejects it).
- **Calculator** is controlled through UI Automation in ORION's own new window, which ORION closes afterwards.
- **Notepad:** ORION only reads or writes the tab it opened itself, matched by exact name; it refuses when several tabs share that name, never opens duplicate copies, and backs up a file before replacing its text.

## What is logged
Task titles, tool ids and arguments (redacted), statuses, evidence strings (file paths, sizes, hash prefixes, window titles), errors, kill-switch use. Stored in `<data_dir>/logs/orion.jsonl` and `<data_dir>/orion.db` (gitignored). File contents read by `files.read` are not logged (evidence has only size and hash). **However**, the step name shows the tool arguments (redacted, cut to 80 characters), so the first part of the text given to `files.write_new` does appear in the log and DB.

## What is never captured
No screenshots, keystrokes, clipboard, microphone or webcam: none of these exist yet.

## Known gaps (honest)
- Redaction is pattern-based; a bare secret in free text is not caught. Do not type secrets into ORION.
- A tool that ignores cancellation keeps running in the background after ORION stops waiting (Python cannot kill threads). All current tools check the token before making changes, but the residual risk is real for future long-running tools.
- `app.launch notepad` can report `verification_failed` when Notepad opens as a tab (see the tools reference).
- Delete has no undo command; files are recoverable from `workspace/.orion_trash/` by hand.
