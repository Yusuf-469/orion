# ORION STATUS

Statuses: planned / in progress / implemented-mock / implemented-real / verified.
Last updated: 2026-10-24 (Stage 1 complete, awaiting gate approval).

## Environment (VERIFIED 2026-10-24, `artifacts/env_audit_raw.txt`)
Win 11 Home 10.0.26200 · i7-13650HX · 23.8 GB RAM · RTX 4060 Laptop 8 GB (~6 GB free at idle), driver 610.88 · 68 GB free disk · displays 1920×1080 @125% and @100%.
Venv: Python 3.11.9 (Microsoft Store base), PySide6 6.12.0, pydantic 2.14.1, pytest 9.1.1, pytest-timeout 2.4.0. **PyTorch in venv: not installed** (system torch is CPU-only 2.10.0+cpu).

## Capabilities

| Capability | Status | Evidence |
|---|---|---|
| Stage 0 audit and report | verified | `docs/stage0_report.md`, commit 93662df |
| Strict config loader (TOML, BOM-tolerant) | verified | `tests/unit/test_config.py` 7 passed, commit ca2d044 |
| JSON-lines logging with redaction | verified | `tests/safety/test_log_redaction.py` 12 passed; caught and fixed a Bearer-token leak |
| Task/step state machine | verified | `tests/unit/test_states_and_store.py` |
| SQLite store (tasks, steps, events) | verified | same file; incl. 4-thread concurrent write test |
| Kill switch (latching, cancels all tasks) | implemented-mock | 10 trials (mock): max 141 ms, mean 64 ms to stop, 0 actions started after stop (run 2026-10-24) |
| STOP button → cancelled and visible in UI | implemented-mock | offscreen UI test: 47 ms; UI max timer gap 36 ms during task |
| Global hotkey (Ctrl+Alt+End) | implemented-real (partial) | `-m real` test: OS registration succeeded and WM_HOTKEY handling engaged the switch. **Physical key press not yet tested** (manual M7) |
| Dry-run mode (default ON) | verified (mock) | executor never calls actions; steps `skipped`, `started_at` NULL |
| Error display | implemented-mock | injected-failure test shows red banner |
| App launch and clean exit | verified | `python -m orion` launched, window "ORION (Stage 1 shell)", WM_CLOSE → exit code 0 (log) |
| Manual UI checklist M1 to M11 | planned | `docs/stage1_manual_checklist.md`, not yet run by the user |
| Tool registry, policy engine (Stage 2) | planned | |
| Planner, task graph, resume (Stage 3) | planned | |
| UIA / browser perception and verification (Stage 4) | planned | |
| Recovery (Stage 5) | planned | |
| Grounding research (Stage 6) | planned | |

## Test totals (2026-10-24)
`-m "not real"` offscreen: **40 passed**. `-m real`: **1 passed**. All action tests are mock: no real desktop control exists yet.

## Open issues
- Master spec `docs/ORION_Master_Technical_Documentation.md` still missing.
- CUDA PyTorch not installed (needs approval; not needed until Week 8).
