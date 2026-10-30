# Tools and Permissions Reference (Stage 2)

Every action ORION takes goes through a **registered tool**. There is no generic shell, script or "run command" tool, and none will be added (project safety rules).

## How a tool call is decided

```
ToolCall(tool_id, args)          extra fields rejected (a call cannot label itself)
  → registry lookup              unknown id → unsupported_capability
  → args schema (Pydantic)       wrong/extra fields → invalid_input        (nothing runs)
  → policy (registered spec)     missing permission → permission_denied    (step BLOCKED)
                                  consequential → ask user (one call only) → declined: confirmation_required (BLOCKED)
  → run with timeout + cancel    timeout / cancel → outcome "uncertain" unless the tool is read-only
  → output schema check          wrong type → unknown (never counted as success)
  → evidence                     every tool re-reads the environment to verify its own effect
```

Retries: only for tools marked **idempotent**, only on `timeout` / `application_unavailable`, within the tool's `max_retries`. Non-idempotent tools are never retried automatically (spec 8.3).

## Permissions

| Permission | Granted by default | Notes |
|---|---|---|
| `files.read` | yes | read and list files: relative paths inside the workspace, full paths anywhere on the PC |
| `files.write` | yes | create new files and copies; never overwrite |
| `app.launch` | yes | allowlisted apps only |
| `files.delete` | **no** | add to `granted_permissions` in `orion.toml`; every delete still asks |

`confirm_reversible = true` in `orion.toml` makes ORION also ask before reversible changes (writes, copies, app launches). Consequential actions **always** ask; no setting turns that off.

## Tools

| Tool | Side effect | Permissions | Idempotent | Timeout | Verification |
|---|---|---|---|---|---|
| `files.read` | read-only | files.read | yes (1 retry) | 10 s | returns the bytes read and their SHA-256 |
| `files.list` | read-only | files.read | yes (1 retry) | 10 s | listing read from disk (max 500 entries, trash hidden) |
| `files.write_new` | reversible | files.write | no | 10 s | exclusive create, fsync, re-read SHA-256 must match |
| `files.copy` | reversible | files.read, files.write | no | 30 s | copy's SHA-256 equals source's |
| `files.delete` | **consequential** | files.delete | no | 10 s | source gone; trash copy has the same SHA-256 |
| `app.launch` | reversible | app.launch | no | 15 s | a **new** visible window for the app appears |

### Paths: workspace by default, anywhere with a full path (2026-10-31)
A relative path is inside `workspace_dir`. A full local path (`C:\...`) reaches any file on the PC: `files.read`, `files.list`, `docs.read_document`, `docs.summarize_csv` (source) and the source of `files.copy` read it without asking. `files.write_new` and the destination of `files.copy` outside the workspace raise the policy decision to **confirm** (`ToolRuntime._decide` + `PolicyEngine.escalate`: a call can raise a decision, never lower it). `files.delete` always confirms. Windows system folders (Windows, Program Files, ProgramData), drive roots, recovery/boot folders and other users' profiles need a **second** confirmation. Full paths still reject UNC/network paths (credential leak), `..`, alternate data streams, device names and aliased names (`tests/safety/test_files_anywhere.py`).

### Relative paths (all file tools)
Relative paths are confined to `workspace_dir` (default `workspace/`, gitignored). Rejected before any disk access: drive-relative paths (`C:x`), UNC paths, `..`, `:` (alternate data streams), reserved device names (`CON`, `NUL`, `COM1`, …), names ending in `.` or space, NUL bytes, and ORION's own `.orion_trash/`. The final check resolves symlinks and junctions and requires the real path to be inside the workspace. Tested with a real junction pointing outside (`tests/safety/test_file_tools.py`).

### Delete is a move
`files.delete` moves the file to `workspace/.orion_trash/<timestamp>_<name>`. There is no undo command yet; restoring means moving it back by hand. The confirmation dialog says so.

### app.launch allowlist
| `app` value | Executable (full System32 path, no shell, no arguments) | Window matched by |
|---|---|---|
| `notepad` | notepad.exe | process `notepad.exe` or title contains "Notepad" |
| `calculator` | calc.exe | `calculatorapp.exe` / title "Calculator" (window is owned by ApplicationFrameHost) |
| `paint` | mspaint.exe | process `mspaint.exe` or title contains "Paint" |

**Known limitation:** Windows 11 Notepad may open a new *tab* in an already-open Notepad window. Then no new window appears and `app.launch` reports `verification_failed`, even though Notepad did respond. This is reported honestly rather than counted as success. UIA-based verification (Stage 4) can fix it.

## Error codes (spec 8.4)
`invalid_input`, `unsupported_capability`, `permission_denied`, `target_not_found`, `stale_state`, `timeout`, `application_unavailable`, `verification_failed`, `confirmation_required`, `cancelled`, `unknown`.

Task/step status mapping: `permission_denied` and `confirmation_required` → **blocked** (nothing ran). Uncertain outcomes → step **needs_review**, task failed. Cancelled → **cancelled**.
