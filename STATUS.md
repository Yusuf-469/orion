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
| Stage 1 checklist M2-M6, M8, M11 | verified (automated, real windows) | `artifacts/acceptance_2026-10-27.json`, commit 770a637, 2 consecutive runs 24/24. Found and fixed a real cancel race (task marked failed instead of cancelled) |
| Stage 2 checklist T1 to T9 | verified (automated, real windows) | same report; T7 uses WM_HOTKEY to ORION's window, T8 launches and closes a real Calculator. Found and fixed stale confirmation dialogs (2nd dialog not found, leak) |
| Stage 3 checklist G1 to G10 (G6 split into G6a/G6b; checklist expectation corrected) | verified (automated, real windows) | same report; G8/G9 = real subprocess crash mid-copy, banner, resume verified without repeat |
| Human-only checks still open | open | M7 physical key press *during a running task* (physical press itself verified Stage 1; handling verified via WM_HOTKEY), M9 visual crispness on 100%/125% monitors. Need the user's eyes; not blocking |
| Research design revised and merged with `docs/proposal_research_depth.md`: P0 re-ranker vs P1 fine-tuned SigLIP/CLIP scorer (pre-registered selection rule), temperature scaling + conformal abstention, synthetic-to-real research question, own tool-calling loop (Wk 4), learned outcome verifier (Wk 10 stretch) | planned (pre-registration draft) | `docs/12_WEEK_PLAN.md` §5; frozen in Week 8 |
| Synthetic UI generator (minimal, HTML + ground truth, 6 families, 6 factor switches, abstain cases) | implemented (no rendering yet) | `src/orion/grounding/synth.py`, `tests/unit/test_synth.py` 11 passed. Self-review found a labelling bug (19% of pages had ambiguous "twins" given a single target); fixed + regression test. Sample batch v0: 60 pages, 449 instructions, 95 abstain. Boxes need Playwright rendering (Stage 4) |
| Stage 3 Week 4 item: LLM planner measured on prompt set v1 | done | see C4 rows above |
| Plan-review step before running any LLM plan | planned (required before the LLM planner is offered in the app) | finding 4 of the C4 report |
| Goal/plan schemas + plan validator | verified (unit) | `tests/unit/test_plan_validator.py` 14 passed |
| Template planner (chaining, clarification, refuses unknown) | verified (unit) | `tests/unit/test_planners.py` |
| Planner eval on fixed prompt set v1 (24 prompts) | measured | template: behaviour 24/24, plan validation 12/15 of proposed (the 3 rejections are the intended escape/device-name prompts), invalid tool calls 0. `research/planner_eval/result_template_v1.json`, commit e7b2372. **Caveat:** prompts written alongside the templates; a baseline, not evidence of generalization |
| LLM planner loop (C4) | implemented-real, measured | Phi-3.5-mini via Ollama (MIT, verified). Constrained, 3 runs at e836e38: behaviour 5/24 each, safe 11/12, exact plan 2/12, 24/24 prompts stable within the session; unconstrained: 0 usable replies. Earlier session: 9-10/24. Full analysis: `research/reports/c4_planner_eval_v1.md`. Verdict: not good enough to plan; containment held in every run |
| Intent-drift check in validator | verified (unit) | catches invented destinations and rewritten paths (post-hoc: 2 bad + 1 strict catch of 10 accepted LLM plans); cannot catch invented content |
| Local LLM runtime | installed (approved 2026-10-27) | Ollama 0.40.11 (winget, installer hash verified), loopback only (verified 127.0.0.1:11434), model 2.03 GiB on disk, 3.8 GB VRAM at ctx 4096 |
| Verifier (read-only checks) | verified | used by every graph test |
| Graph runner: deps, priority order, checkpoints, outcomes (spec 9), cancel, dry-run of whole plan | verified (real disk, tmp dir) | `tests/integration/test_graph_runner.py` |
| Crash-safe resume (gate S6) | verified (real crash) | subprocess `os._exit` mid-tool: completed step not repeated; verifiable step "verified after resume"; unverifiable step needs_review, **0 repeats**; read-only step re-run. 3 tests |
| Schema v2 migration with automatic backup | verified (real) | user's `data/orion.db` migrated 2026-10-27; `data/orion.db.v1.bak` created |
| History inspect/delete (spec 10) | implemented-mock (offscreen) | `tests/integration/test_goal_ui.py` |
| Goal box, resume banner in UI | implemented-mock (offscreen) + app launch verified | `test_goal_ui.py`; app launched as "ORION (Stage 3)", exit 0 |
| Stage 3 manual checklist G1 to G10 | planned | `docs/stage3_manual_checklist.md` |
| UIA / browser perception and verification (Stage 4) | planned | |
| Recovery (Stage 5) | planned | |
| Grounding research (Stage 6) | planned | |

## Test totals (2026-10-24, end of session)
`-m "not real"` offscreen: **190 passed** (2026-10-27). `-m real`: **2 passed** (hotkey message handling, Calculator launch). Crash tests run real subprocesses.

## RESUME HERE (Stages 1 to 3 closed)
2026-10-27: all Stage 1-3 checklists verified by a scripted real-window acceptance run (24/24, twice); real-LLM planner measured (C4 baseline). Waiting for approval to start Stage 4 (Windows UIA + browser control). Only human-eye checks remain open (M7 during a task, M9 DPI look).

## Open issues
- Spec-alignment gaps to schedule: B5 visual-matching baseline (planner edit pending approval), "partially complete"/"unverified" outcomes (Stage 3/4), history inspect/delete controls (Stage 3). See `docs/stage0_report.md` §10.
- CUDA PyTorch not installed (needs approval; not needed until Week 8).
