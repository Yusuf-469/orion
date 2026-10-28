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
| Plan-review step before running any LLM plan | implemented-mock (offscreen) | opt-in `planner = "llm"`; review dialog default No; invalid plans never reach review; `tests/integration/test_goal_ui.py`. Commit 76c1d08 |
| C4 iteration 2 (fixes + dev-set tuning + one final v1 test) | measured | v1: behaviour 5→8/24, safe 11→12/12, exact plan 2→4/12, 3 reload-separated runs identical (reload hypothesis rejected). Dev paraphrases: LLM 6/8 vs template 3/8. Found and fixed an ORION schema bug that depressed all earlier constrained results. `research/reports/c4_planner_eval_v1.md` |
| Content-drift check (invented / empty file text) | verified (unit) | `test_plan_validator.py` |
| Quote-aware clause splitting; file text never in logs/step names | verified | `test_planners.py`, `test_tool_console.py` |
| Eval safety: health check, abort on lost server | verified (unit + caught a real dead-server run) | `test_ollama_backend.py` |
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
| Notepad control via UI Automation (open file, read, set text + save with backup, close own tab) | verified (real) | `tests/integration/test_notepad_real.py`. Privacy guard: only the active tab ORION opened is ever read/written (Win 11 Notepad restores the user's tabs) |
| Browser: read table / text from local pages (headless Chromium, throwaway profile) | verified (real) | `tests/integration/test_browser_docs.py`; non-local URLs and paths outside the workspace refused |
| CSV write + summarize (new files only, read-back verified) | verified | same file |
| **First end-to-end demo** (web table → report.csv → summary.txt → Notepad, screen checked against disk) | verified (real) | `tests/end_to_end/test_demo_slice.py`; **10/10 consecutive real runs** 2026-10-28, commit 155fdfa |
| Prompt injection on the demo page cannot change the plan | verified | plan fixed before the page is read; page text returned as untrusted data only |
| Form filling in a visible browser, stops before submit (no submit tool exists) | verified (real) | `tests/end_to_end/test_form_fill.py`; values must come from the request |
| Recovery: dialog blocking Notepad (ask, then close like Cancel) / lost tab (reselect), one retry per step | verified (real) | `tests/end_to_end/test_recovery.py`, 3 scenarios, repeated 3/3 and 5/5 after fixes |
| Notepad safety fixes | verified | no duplicate copies (reselect existing tab), exact tab matching, refuse ambiguous names, harmless pop-ups not treated as dialogs, library log disabled |
| Leftover test tabs in the user's Notepad session | resolved | 2026-10-28: session back to 5 tabs, 0 test tabs; tests now use unique names and verify cleanup |
| Recovery (Stage 5) | planned | |
| Calculator control (UIA Invoke, own window, display checked against own maths) | verified (real) | `tests/end_to_end/test_calculator.py` |
| Examples menu in the app | verified (offscreen) | every example plans validly (`test_goal_ui.py`) |
| **Visual grounding v1** (UIA + local OCR, rule-based fusion with abstention) | verified (real) | `tests/end_to_end/test_visual_click.py`: clicks buttons that only exist as pixels; refuses a missing button; never confuses "Close Report" with the window's Close; also verified on the 125% monitor (manual probe 2026-10-28) |
| Grounding data: 600 rendered synthetic pages (boxes + metadata + OCR) | done | `research/data_collection/render_synth.py` (data gitignored, regenerable from seeds) |
| **P0 learned grounding scorer, live in the product** | verified (held-out families + real app) | correct 63.1% -> 90.3%, wrong clicks 1.0% -> 0.8% vs rules; CI +25.8..+28.7 pts; real canvas clicks on both monitors. `research/reports/grounding_v1.md` |
| Conformal abstention | measured | coverage 90.7%/95.9% in-distribution, 89.4%/96.4% held-out; not used as click rule (more wrong clicks) |
| Frozen SigLIP features / P1 LoRA fine-tune | measured, not shipped | +2 pts correct, no fewer wrong clicks; P1 no gain over frozen (negative result) |
| **"Did you mean A or B?"** (screen.click asks when several places match, clicks only the one picked) | verified (real) | 2026-10-28: canvas demo with two "Export" buttons, pick centre -> "Export #2", pick top -> "Export #1", exactly one click each; no answer -> step blocked, nothing clicked (`tests/end_to_end/test_visual_click.py`, 6 passed x2); dialog offscreen (Neither/STOP = no click); plans cannot set the pick (`user_only_argument`). Choices come from duplicate-label / margin ties, not conformal sets |
| Grounding on real apps (Calculator, Paint, Character Map; ORION's own windows, nothing clicked) | measured | `research/reports/grounding_real_v1.md`: 0 wrong clicks with metadata; found + fixed nested-element bug (`collapse_nested`, learned 68% -> 79% correct); rules 87.5% beat learned on real apps (synthetic-to-real gap); OCR alone finds ~10% (icons) |
| GPU stack | installed (approved) | torch 2.11.0+cu128 on RTX 4060, transformers 5.21, peft 0.21, scikit-learn 1.9.1, SigLIP base (Apache-2.0) |

## Test totals (2026-10-24, end of session)
`-m "not real"` offscreen: **204 passed** (2026-10-27). `-m real`: **2 passed** (hotkey message handling, Calculator launch). Crash tests run real subprocesses.

## RESUME HERE (Stage 6 core done)
2026-10-28: learned grounding scorer live (90% correct on unseen layouts, fewer wrong clicks than rules); conformal analysis, frozen and fine-tuned SigLIP measured (not shipped); "did you mean A or B?" live. Latest totals: `-m "not real"` 239 passed, `-m real` 20 passed + 1 skipped (hotkey held by a running ORION). Next options: real-app grounding test set (Paint/Settings screenshots), benchmark (Stage 9). Open: human-eye checks M7/M9.

## Open issues
- Spec-alignment gaps to schedule: B5 visual-matching baseline (planner edit pending approval), "partially complete"/"unverified" outcomes (Stage 3/4), history inspect/delete controls (Stage 3). See `docs/stage0_report.md` §10.
- CUDA PyTorch not installed (needs approval; not needed until Week 8).
