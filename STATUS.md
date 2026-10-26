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
| Kill switch reports "stopping N task(s)" until uninterruptible actions end (spec 11.6) | implemented-mock | `test_uninterruptible_action_reported_honestly`, commit 1f82cf7 |
| STOP button → cancelled and visible in UI | implemented-mock | offscreen UI test: 47 ms; UI max timer gap 36 ms during task |
| Global hotkey (Ctrl+Alt+End) | implemented-real (partial) | `-m real` test: OS registration succeeded and WM_HOTKEY handling engaged the switch. **Physical key press not yet tested** (manual M7) |
| Dry-run mode (default ON) | verified (mock) | executor never calls actions; steps `skipped`, `started_at` NULL |
| Error display | implemented-mock | injected-failure test shows red banner |
| App launch and clean exit | verified | `python -m orion` launched, window "ORION (Stage 1 shell)", WM_CLOSE → exit code 0 (log) |
| Physical hotkey press engages kill switch | verified (real) | `data/orion.db` event 2026-10-24 01:20:54 "kill switch engaged via hotkey ctrl+alt+end" from the user's key press |
| Manual UI checklist M1 to M11 | partially verified | User reported "working" 2026-10-24. Evidence in DB: M1 (launch) and the hotkey engaging the switch. No tasks were recorded, so M2 to M6 and M8 to M11 have **no stored evidence**; M7 is only partly shown (switch engaged, but no running task to cancel). |
| Tool contract, error taxonomy (spec 8.1/8.4), registry | implemented-mock | `tests/safety/test_policy_and_runtime.py` |
| Policy engine (allow/confirm/deny; consequential always confirms; no relabel) | implemented-mock | same file, 22 passed |
| Runtime: timeout, cancel (incl. during confirmation), retries only for idempotent tools, uncertain outcomes flagged | implemented-mock | same file |
| File tools in workspace (read, write_new, copy, list, delete→trash) with read-back verification | implemented-real (tmp dir) | `tests/safety/test_file_tools.py` 30 passed, incl. real junction-escape test |
| app.launch (notepad/calculator/paint allowlist) with new-window verification | implemented-real | real test: Calculator window verified in 0.22 s, closed by the test |
| UI tool console and confirmation dialog (kill switch closes it) | implemented-mock (offscreen) | `tests/integration/test_tool_console.py` |
| Stage 2 docs: `docs/tools-and-permissions.md`, architecture v2, safety-and-privacy v2 | implemented | 2026-10-27 |
| Stage 2 manual checklist T1 to T9 | **not run** | 2026-10-27: DB has no tasks, no `workspace/` folder. User said "continue"; Stage 3 started on that approval. Automated Stage 2 tests cover the same behaviours offscreen. |
| Research design revised and merged with `docs/proposal_research_depth.md`: P0 re-ranker vs P1 fine-tuned SigLIP/CLIP scorer (pre-registered selection rule), temperature scaling + conformal abstention, synthetic-to-real research question, own tool-calling loop (Wk 4), learned outcome verifier (Wk 10 stretch) | planned (pre-registration draft) | `docs/12_WEEK_PLAN.md` §5; frozen in Week 8 |
| Synthetic UI generator, background track Weeks 4 to 7 | planned | starts with Stage 3 |
| Planner, task graph, resume (Stage 3) | planned | |
| UIA / browser perception and verification (Stage 4) | planned | |
| Recovery (Stage 5) | planned | |
| Grounding research (Stage 6) | planned | |

## Test totals (2026-10-24, end of session)
`-m "not real"` offscreen: **109 passed**. `-m real`: **2 passed** (hotkey message handling, Calculator launch).

## RESUME HERE (Stage 2 gate)
Stage 2 code, tests and docs are done. Waiting for: the user's run of `docs/stage2_manual_checklist.md`, then approval to start Stage 3 (goals, task graph, planner, persistence, resume).

## Open issues
- Spec-alignment gaps to schedule: B5 visual-matching baseline (planner edit pending approval), "partially complete"/"unverified" outcomes (Stage 3/4), history inspect/delete controls (Stage 3). See `docs/stage0_report.md` §10.
- CUDA PyTorch not installed (needs approval; not needed until Week 8).
