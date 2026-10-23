# ORION: 12-Week Master Planner

**Companion to:** `docs/ORION_Master_Technical_Documentation.md` (the authoritative spec; this planner never overrides it).
**Project:** ORION, a general-purpose autonomous Windows computer-use agent.
**Developer:** one person (solo). **Machine:** Windows laptop with an NVIDIA GPU (exact model, VRAM and driver are **UNVERIFIED until Week 1 measures them**).
**Budget:** ₹0 core (free and open-source tools, local execution; paid APIs optional and off by default).
**Two priorities:** (1) a reliable end-to-end demo, (2) one genuine, measurable ML research contribution.

> **Evidence labels used throughout.** `VERIFIED` = I ran or read it and can show the output. `ASSUMPTION` = believed but not checked. `PROPOSED` = a design or target I am suggesting. `UNTESTED` = built or planned but not run for real. Everything in this planner is `PROPOSED` or `ASSUMPTION` until a week's evidence says otherwise. Targets are goals to be re-set after Week 1 measurements, not results.

> **Week 1 update (2026-10-24):** hardware measured. See `docs/stage0_report.md` (RTX 4060 Laptop 8 GB, ~6 GB free at idle; i7-13650HX; 24 GB RAM; mixed 100%/125% DPI).

---

## 0. How to use this planner

1. Work one week at a time. Each week ends at a **gate**. Do not start the next week until the gate evidence exists (commands, test output, commit hashes in `STATUS.md`).
2. Every week has: goal, tasks, deliverables, acceptance criteria, tests, docs, what to demo, and what to cut if behind.
3. Update `STATUS.md` (capability table) at the end of every working session.
4. If a week slips by more than 3 days, apply the **cut rules** in section 9. Never cut safety, verification or honest reporting.
5. Keep the full vision. Anything not in the MVP is **deferred**, not deleted (section 2).

### Assumed time budget (ASSUMPTION, adjust after Week 1)
- About **15 to 20 focused hours per week** alongside college and placements.
- Weekday evenings about 2 hours, weekends about 5 to 6 hours per day.
- Weeks with placement visits or exams are marked **LIGHT** and carry slack.

### Proposed calendar (ASSUMPTION: starts Sat 24 Oct 2026; shift if college exams or project reviews differ)
| Week | Dates | Stage | Theme |
|---|---|---|---|
| 1 | 24 to 30 Oct | 0 | Environment audit, repo, architecture, experiment design (**LIGHT**: placement events) |
| 2 | 31 Oct to 6 Nov | 1 | Desktop shell, logging, kill switch, dry-run |
| 3 | 7 to 13 Nov | 2 | Tool contracts, registry, policy engine, file/app tools |
| 4 | 14 to 20 Nov | 3 | Goals, task graph, planner, persistence, resume |
| 5 | 21 to 27 Nov | 4a | Windows UI Automation: perception, actions, verification |
| 6 | 28 Nov to 4 Dec | 4b | Browser control; **first end-to-end vertical slice (Gate A)** |
| 7 | 5 to 11 Dec | 5 | Recovery, idempotency, interruption, safety tests |
| 8 | 12 to 18 Dec | 6a | Grounding dataset, annotation protocol, baselines, frozen splits |
| 9 | 19 to 25 Dec | 6b | Hybrid method: training/adaptation and evaluation (**Gate B**) |
| 10 | 26 Dec to 1 Jan | 6c | Integrate grounding, error analysis, latency; optional Stage 7 |
| 11 | 2 to 8 Jan | 9a | Benchmark suite, three-condition comparison, ablations |
| 12 | 9 to 15 Jan | 9b | Packaging, clean-machine test, docs, report, demo rehearsal (**Gate C**) |

Stage 8 (extra modalities) is **deferred** past Week 12 unless Week 10 or 12 has spare time.

---

## 1. Vision and boundaries (preserved from the spec)

**ORION is** a goal-oriented agent that interprets a high-level goal, builds a plan, selects tools, observes the real environment, acts with permission, verifies the result, recovers or replans when safe, and reports what was actually achieved.

**ORION is not** only a voice assistant, a list of hard-coded commands, a promise of perfect autonomy, a way to bypass UAC/authentication/privacy, a claim that every USB device works without a driver, or a research contribution just because a pretrained model is called. Model confidence is never proof.

**Design principles:** outcome-oriented, hybrid intelligence (deterministic where precise, ML where it helps), tool-agnostic typed interfaces, local-first, permission-aware (policy enforced outside the language model), transparent, incremental, evidence-driven.

---

## 2. Complete capability register

Nothing from the spec is removed. "MVP" = built and verified within 12 weeks. "Stretch" = built only if schedule allows. "Deferred" = kept in the roadmap, post-Week 12.

### 2.1 Subsystems (spec section 4)
| # | Subsystem | Plan | First built |
|---|---|---|---|
| 1 | Interaction layer (text input, task monitor) | MVP (text and keyboard) | Wk 2 |
| 1b | Optional speech in/out, alternative input | Deferred (modular, push-to-talk first) | after Wk 12 |
| 2 | Intent/context engine (structured goal, constraints, missing info) | MVP | Wk 4 |
| 3 | Planner/orchestrator (task graph, dependencies, checkpoints, replanning) | MVP | Wk 4, 7 |
| 4 | Perception (UIA metadata, DOM, OCR, screenshots, app state) | MVP | Wk 5, 6, 8 |
| 5 | Tool registry (schemas, permissions, side effects, result contracts) | MVP | Wk 3 |
| 6 | Execution runtime (timeouts, cancellation, result records) | MVP | Wk 3 |
| 7 | Verification engine (pre/postconditions, goal completion) | MVP | Wk 5, 6 |
| 8 | Recovery engine (error classes, safe recovery, escalation) | MVP | Wk 7 |
| 9 | State/memory store (tasks, checkpoints, approved preferences, logs) | MVP | Wk 2, 4 |
| 10 | Policy engine (independent authorization and confirmations) | MVP | Wk 3 |
| 11 | Observability (structured logs, traces, metrics, progress) | MVP | Wk 2 |
| 12 | ML experiment pipeline (data, annotation, training, versioning, eval) | MVP | Wk 8 to 10 |

### 2.2 Scope items (spec section 3)
| Item | Plan |
|---|---|
| Windows desktop shell, task input and monitoring | MVP, Wk 2 |
| Structured intent and task planning | MVP, Wk 4 |
| Typed tool registry and safe runtime | MVP, Wk 3 |
| Windows UI Automation and browser automation | MVP, Wk 5 and 6 |
| Bounded file and document operations | MVP, Wk 3 (files), Wk 6 (documents: csv/txt/xlsx) |
| Persistent state, logs, resume | MVP, Wk 4 and 7 |
| Verification, error handling, cancellation, recovery | MVP, Wk 2, 5, 7 |
| Model configuration and repeatable tests | MVP, Wk 2 onward |
| Screenshot visual grounding and OCR | MVP (the research contribution), Wk 8 to 10 |
| Learned action-outcome prediction | Stretch, Wk 10 |
| Model adaptation or fine-tuning | Stretch within Wk 9 if compute/licence allow |
| Demonstration-based workflow learning | Deferred (offline research only) |
| Local language-model integration | MVP if hardware allows (planner backend), else rule-based plus optional hosted |
| Webcam head-pose or gesture input | Deferred |
| USB/assistive device integrations (documented APIs only) | Deferred |
| Packaged Windows release and research report | MVP, Wk 12 |

### 2.3 Non-goals for the first release (unchanged)
No large vision-language model trained from scratch; no universal app compatibility; no unattended purchases, messages, submissions or important deletions; no covert microphone/webcam capture; no claim that ordinary webcam gaze equals dedicated eye tracking; no cloud service before the local prototype works; no presenting unimplemented features as working.

### 2.4 Representative scenarios (spec 3.4), mapped to the benchmark
| Scenario | Benchmark category | Built by |
|---|---|---|
| Cross-application research | cross-app | Wk 11 (fixtures, no live web accounts) |
| Document workflow (preserve original, edit a copy, reopen to verify) | multi-step | Wk 6 |
| Browser form preparation (stop before submission) | multi-step | Wk 6 |
| Development workflow (run tests, capture logs, report exact result) | multi-step | Wk 11 (stretch) |
| Unexpected UI state (dialog appears) | failure/recovery | Wk 7 |
| Long-running workflow (checkpoint, resume after interruption) | interruption | Wk 7 |

---

## 3. Architecture (PROPOSED; confirm in Week 1)

```
User goal --> Interaction layer --> Intent/context engine --> Planner (task graph)
                                                                |
        +-------------------- observe/plan/act/verify/recover loop ---------------+
        |  Perception <--- environment (Windows UIA, browser DOM, OCR, screenshots)|
        |  Policy engine (authorize, confirm) --> Executor --> Tool registry       |
        |  Verifier (postconditions) --> Recovery engine --> Planner (replan)      |
        +--------------------------------------------------------------------------+
        State store (SQLite: tasks, checkpoints, logs)    Observability (JSON logs)
```

**Control loop (spec 4.1):** receive request, structure the goal, validate constraints and permissions, generate and validate the task graph, pick an eligible step, observe, choose and validate an action, policy check, execute, observe again, evaluate postconditions, then mark complete, recover, replan, ask, or stop safely; persist a checkpoint; repeat until verified, blocked, cancelled or stopped.

**Hard rules enforced in code, not prompts:** allowlisted tools only; schema-validated arguments; no arbitrary model-generated shell commands; policy checks outside the model; webpage/document content treated as untrusted data; every consequential action requires explicit confirmation; cancellation stops new actions immediately; success is never assumed from a command being issued.

### 3.1 Repository layout (spec section 13, kept)
```
orion/
  README.md  LICENSE  pyproject.toml  CLAUDE.md  STATUS.md
  docs/        architecture.md  safety-and-privacy.md  model-card-template.md
               dataset-card-template.md  evaluation-protocol.md  release-checklist.md
               ORION_Master_Technical_Documentation.md  12_WEEK_PLAN.md  stage0_report.md
  src/orion/   app/ interaction/ intent/ planner/ orchestration/ perception/ grounding/
               tools/windows/ tools/browser/ tools/files/ tools/documents/
               execution/ verification/ recovery/ policy/ memory/ observability/ models/ config/
  tests/       unit/ integration/ safety/ fixtures/ end_to_end/
  research/    data_collection/ annotations/ baselines/ training/ evaluation/ reports/
  scripts/  artifacts/
```

### 3.2 Candidate stack (PROPOSED; every item needs a Week 1 licence, size and Windows check)
| Area | Candidate | Note |
|---|---|---|
| Language | Python | ML plus automation ecosystem |
| UI shell | PySide6 | check LGPL licence terms |
| Schemas | Pydantic | typed validation |
| Async | asyncio | long-running tasks, cancellation |
| Persistence | SQLite | tasks, checkpoints, logs |
| ML | scikit-learn, PyTorch (CUDA build matched to the measured driver) | baselines, training |
| Vision | OpenCV plus pretrained models chosen after the audit | candidates to verify, not assumed: OmniParser, ShowUI, UI-TARS, Florence-2, OWL-ViT; licences and VRAM unverified |
| Windows control | UI Automation via pywinauto and/or uiautomation | semantic desktop interaction |
| Browser | Playwright | DOM automation |
| OCR | one local engine (e.g. Tesseract, EasyOCR or PaddleOCR) chosen by a Week 8 bake-off | accuracy and speed on UI text |
| Tests | pytest | unit, integration, safety |
| Packaging | PyInstaller | clean-machine test in Wk 12 |

---

## 4. First vertical slice (PROPOSED; built in Wks 5 to 7, demonstrated Wk 6 and 7)

**Task "Fixture report":** On a controlled local fixture page, extract a table of 5 rows, create `report.csv` and a short `summary.txt` in an authorized output folder (via the bounded file tool), open the summary in Notepad through UI Automation, verify its contents on screen and on disk, then stop. A second run injects an unexpected dialog (for example a "file exists, overwrite?" prompt) and ORION must detect it, recover or ask, and finish or stop safely.

**Why this slice:** it crosses a browser, the file system and a desktop app, uses perception from three sources, has real postconditions, and has a natural failure to recover from, while using only fixtures and no real accounts.

### Acceptance criteria (PROPOSED thresholds; re-set after Week 1 measurements)
| ID | Criterion | Target |
|---|---|---|
| S1 | Clean runs verified successful | at least 9 of 10 |
| S2 | Injected-dialog runs recovered or safely stopped (no wrong action taken) | 10 of 10 safe; at least 7 of 10 recovered |
| S3 | Postconditions checked by reading the result (file content, screen state), never inferred from the command | 100% of steps |
| S4 | Unauthorized or consequential action taken without confirmation | 0 |
| S5 | Kill switch stops new actions | within 2 seconds, every time |
| S6 | Resume after forced interruption re-observes before acting and does not repeat uncertain side effects | pass |
| S7 | Every run produces a structured log with step, evidence and verdict | 100% |

---

## 5. Pre-registered research experiment: hybrid UI visual grounding (PROPOSED; freeze in Week 8, before any tuning)

**Research question.** Can a hybrid (or adapted) visual-grounding approach select the correct UI element for a natural-language instruction more reliably than accessibility-metadata-only and OCR-only baselines, especially on unfamiliar layouts?

**Task.** Input: screenshot plus instruction (for example "the Export button in the report toolbar"). Output: bounding box, element class, text, confidence, or **abstain**. A prediction is correct if IoU with the annotated box is at least 0.5 (also report a stricter 0.7).

**Data (permitted and sanitized only).**
- Synthetic web UIs generated from HTML templates with randomized layouts, themes (light/dark), display scaling (100/125/150%), languages of labels, and ground truth taken from the DOM.
- Screenshots of safe Windows apps (Notepad, Calculator, Paint, Settings pages without personal info) with annotations.
- No personal messages, credentials, financial or health content.
- Target size (PROPOSED, subject to annotation effort): at least 1,500 instruction-target pairs, with duplicates, disabled, hidden and missing-target cases included.

**Annotation protocol.** Written rules for nested controls, duplicate labels, disabled and hidden elements, missing targets and ambiguous instructions; double-annotate 15% to 20% and report agreement; resolve disagreements by a written rule.

**Splits (leakage control).** Split by application and layout family, not by random screenshot. At least 30% of layout families held out for test and never seen in training or tuning. Freeze the test set and its hash before any tuning. No near-duplicate screenshots across splits.

**Baselines.**
| ID | Method |
|---|---|
| B1 | Accessibility/DOM metadata lookup only |
| B2 | OCR plus exact/fuzzy text matching only |
| B3 | Pretrained grounding or detection model, zero-shot, no adaptation |
| B4 | Simple rule-based fusion of B1 to B3 (no learning) |
| P | **Proposed hybrid:** candidate generation from UIA/DOM, OCR boxes and a detector, then a learned re-ranker and calibrated abstention (start with gradient-boosted or logistic features: text similarity, role, position, size, visual embedding similarity; adapt a small model only if VRAM and licences allow) |

**Metrics.** Correct target-selection rate (headline), IoU hit rate at 0.5 and 0.7, precision/recall, accuracy on unseen layouts, abstention quality (precision and recall of abstaining on missing/ambiguous targets), latency, peak RAM and VRAM. Report sample counts and bootstrap confidence intervals. Report per-slice error analysis (control type, theme, scaling, ambiguity).

**Ablations (in the harness only, never with safety disabled on the live desktop).** Remove each of: metadata features, OCR features, visual detector, re-ranker, abstention.

**Reporting rules.** Report negative results. No invented numbers. Record model versions, licences, seeds, hardware, data version and config for every result.

**Secondary (Stretch, Week 10): action-outcome prediction.** Features: tool and action type, discovery method, model confidence, enabled/disabled state, expected versus observed transition, timeout/exception class, attempts, UI-change indicators, verification result. Labels: verified success, confirmed failure, unexpected transition, inconclusive. Start with logistic regression or a decision tree, compare with explicit rules on held-out runs. It never replaces postcondition verification and never authorizes a consequential action.

**Tertiary (Deferred): demonstration-based learning.** Offline only, permissioned recordings in a controlled environment.

---

## 6. Week-by-week plan

Each week: **Goal / Tasks / Deliverables / Acceptance (gate) / Tests / Docs / Demo / Cut if behind.**

### Week 1: Stage 0 environment audit and design (LIGHT)
- **Goal.** Know the real machine and lock the design.
- **Tasks.** (1) Read-only audit: Windows version, Python versions, Git, VS Code, CPU, RAM, free disk, GPU, VRAM, driver and CUDA, display resolution and scaling, installed PyTorch/Playwright/pywinauto/OCR. (2) Inspect the existing repo and files; preserve everything. (3) Create the repo skeleton, `CLAUDE.md`, `STATUS.md`, spec in `docs/`. (4) Licence, size and VRAM check for each stack candidate; pick the minimum viable set. (5) Confirm architecture and repo layout. (6) Define the vertical slice and fixtures list. (7) Draft the experiment protocol (section 5). (8) Draft the 12-week schedule against real hours. (9) Risk register.
- **Deliverables.** `docs/stage0_report.md`, environment report with raw command output, confirmed stack, repo skeleton committed.
- **Acceptance.** Every finding labelled VERIFIED/ASSUMPTION/PROPOSED; no hardware claim without measurement; one representative end-to-end task chosen.
- **Tests.** Environment script runs and its output is saved.
- **Demo.** Walk through the report.
- **Cut if behind.** Defer the full licence table for stretch models; keep the core set.

### Week 2: Stage 1 desktop shell
- **Goal.** A launchable app that shows tasks, progress, logs, and can always be stopped.
- **Tasks.** PySide6 main window; task input box; task list with status; live event log pane; configuration file loader; structured JSON logging with secret redaction; SQLite schema (tasks, steps, events); **global kill switch** (button plus hotkey) and **dry-run mode** (plan and show actions, execute nothing); error display; responsive UI (work off the UI thread).
- **Deliverables.** Running shell, log files, DB schema, config reference.
- **Acceptance.** App launches on the target machine; UI stays responsive during a simulated long task; errors and cancellation are visible; kill switch cancels a simulated task within 2 seconds (S5 early check).
- **Tests.** Unit tests for config, log redaction, state transitions; a manual UI checklist.
- **Docs.** `architecture.md` v1, `safety-and-privacy.md` v1 (what is logged, what is never logged).
- **Demo.** Start, run a fake task, cancel it, view logs.
- **Cut if behind.** Skip theming and polish; keep kill switch and dry-run.

### Week 3: Stage 2 tool contracts, registry, policy engine
- **Goal.** Safe, typed, testable tools before any real control.
- **Tasks.** Tool base class and registry with: ID, version, description, input/output schema, required permissions, side-effect category (read-only, reversible local change, consequential), timeout and retry rules, idempotency class, cancellation support, verification method, logging; structured error taxonomy (invalid input, unsupported capability, permission denied, target not found, stale state, timeout, application unavailable, verification failed, confirmation required, cancelled, unknown); policy engine v1 (authorize, require confirmation, deny); bounded file tools (read, write-new, copy, list) restricted to an authorized workspace folder with backups for edits; app-launch tool with an allowlist; execution runtime with timeouts and cancellation; confirmation dialog in the UI.
- **Deliverables.** Registry, policy engine, file and launch tools, confirmation flow.
- **Acceptance.** Invalid arguments and denied permissions fail safely with structured errors; path traversal and out-of-workspace access are blocked; a model cannot relabel a consequential action as harmless; cancellation is tested.
- **Tests.** Unit tests per tool; `tests/safety/` for path traversal, relabel attempts, denied tool, timeout, cancellation.
- **Docs.** Tool registry and permission reference.
- **Demo.** Run the file tools through the policy engine, trigger a denial and a confirmation.
- **Cut if behind.** Ship only file-read, file-write-new and app-launch; defer copy and list.

### Week 4: Stage 3 goals, task graph, planner, persistence, resume
- **Goal.** Turn a request into a validated, resumable plan.
- **Tasks.** Goal schema (ID, objective, constraints, deliverables, authorized outputs, completion checks, risk, missing info); task-graph schema with statuses `pending, ready, running, waiting_for_user, blocked, succeeded, failed, cancelled, skipped, needs_review`; planner interface with two backends: a deterministic template planner (always available) and an LLM-backed planner (local model if hardware allows, otherwise a configurable external API, off by default); **plan validator** (schemas, dependencies, tool existence, permissions, required inputs, contradictions, reversible-before-irreversible, checkpoints before consequential steps); clarification handling for missing information; checkpoints saved transactionally; resume that re-observes before acting and does not blindly repeat uncertain external actions.
- **Deliverables.** Planner, validator, persistence, resume logic.
- **Acceptance.** Multi-step state is correct; invalid or hallucinated plans are rejected (invented tools, missing deps, cyclic graphs); resume after a forced crash does not repeat completed or uncertain actions (S6 on fake tools).
- **Tests.** Property-style tests for graph validity; crash/resume tests; planner tests on a fixed prompt set (record plan validation rate and invalid-tool-call rate).
- **Demo.** Plan a fake multi-step task, kill the app mid-run, resume.
- **Cut if behind.** Use only the template planner; keep the LLM backend as an interface stub.

### Week 5: Stage 4a Windows UI Automation
- **Goal.** Observe and act on real desktop apps with verification.
- **Tasks.** Perception module returning a normalized observation (window, element tree, roles, names, states, bounding boxes, timestamp); element finders with re-acquisition after state changes (stale references handled); UIA action tools (focus, click, type, key, read text, wait-for) on a **controlled app set** (Notepad, Calculator, a small local fixture Qt/Tk app); verification engine v1 (precondition and postcondition checks with evidence); screenshots opt-in and stored only for the fixture runs; display scaling handled and recorded.
- **Deliverables.** UIA tools, observation schema, verifier, fixture app.
- **Acceptance.** Controlled end-to-end tests run on **real** local apps, and real actions are labelled separately from mock ones; postconditions come from reading the result; failures are classified.
- **Tests.** Real-app tests (marked `real`) and mock tests (marked `mock`); report counts for each separately.
- **Docs.** Perception and verification notes; known UIA limits found in practice (custom-rendered controls, duplicate labels).
- **Demo.** Open Notepad, type a line, save to the workspace, verify the file content.
- **Cut if behind.** Support only Notepad plus the fixture app.

### Week 6: Stage 4b browser control and **first vertical slice** (Gate A)
- **Goal.** Complete the slice in section 4 (clean run).
- **Tasks.** Playwright browser tools (open local URL, read DOM text and table, fill fields, click, wait, screenshot opt-in); DOM and accessibility perception; local fixture pages (table page, form page with validation, a page containing a deliberate prompt-injection string); form-fill tool that **stops before submission**; document tools for csv/txt/xlsx (create new, read, verify); wire the end-to-end slice through planner, policy, tools and verifier; demo script.
- **Deliverables.** Browser tools, fixtures, working slice (clean path).
- **Acceptance (Gate A).** S1 measured over 10 runs on the target machine; S3, S4, S7 pass; the injection string on the fixture page does not change the plan.
- **Tests.** End-to-end tests, injection test, form-stop test.
- **Demo.** Run the slice live. Record a short screen recording as evidence.
- **Cut if behind.** Replace xlsx with csv only.

### Week 7: Stage 5 recovery, idempotency, interruption, safety
- **Goal.** Behave sensibly when things go wrong.
- **Tasks.** Recovery engine (stop dependents, capture error and state, assess side effects, revalidate preconditions, pick a safe recovery, policy-check it, bounded retries, verify, replan or ask); failure injection harness (unexpected dialog, missing element, stale element, slow app, permission denied, closed window, forced crash); idempotency (action IDs, state inspection before retry, never repeat just because a response was delayed); duplicate-submission guards for non-idempotent actions; interruption and resume tests; complete the safety test suite (policy bypass, prompt injection, cancellation prevents further actions, missing permission stops safely, log redaction, uncertain target never triggers a high-impact action).
- **Deliverables.** Recovery engine, injection harness, safety suite, updated slice including the dialog case.
- **Acceptance.** S2, S4, S5, S6 pass; injected failures are classified; unresolved consequential states stop safely.
- **Tests.** All safety tests pass or are listed honestly as failed/blocked with reasons.
- **Docs.** Safety and recovery behaviour, known gaps.
- **Demo.** Slice with an injected dialog; kill switch mid-run; resume after crash.
- **Cut if behind.** Limit failure types to dialog, missing element, timeout, crash.

### Week 8: Stage 6a grounding dataset, annotation protocol, baselines, frozen splits
- **Goal.** A trustworthy dataset and honest baselines before any model training.
- **Tasks.** Finalize the protocol in section 5; build the synthetic UI generator (randomized layouts, themes, scaling) with DOM ground truth; capture safe-app screenshots; build a light annotation tool or use an open-source one; double-annotate a subset and compute agreement; split by layout family; **freeze and hash the test set**; implement B1, B2 (OCR bake-off decides the engine), B3, B4; evaluation harness that outputs the metrics and confidence intervals; dataset card.
- **Deliverables.** Dataset v1 (with provenance), frozen splits, baseline results, evaluation harness, dataset card.
- **Acceptance.** Splits documented and leak-checked; baselines run end to end; numbers recorded exactly as measured.
- **Tests.** Split-leakage test (no shared layout family), metric unit tests on toy cases.
- **Demo.** Baseline table on the validation split only (test split untouched).
- **Cut if behind.** Reduce to the synthetic set plus Notepad/Calculator; lower the target size and say so in the report.

### Week 9: Stage 6b hybrid method and evaluation (Gate B)
- **Goal.** Train or adapt P and test it fairly.
- **Tasks.** Candidate generation; feature extraction; re-ranker training with cross-validation on the training layout families only; calibrated abstention; optional small-model adaptation if VRAM and licence allow; hyper-parameter tuning on validation only; one final evaluation on the frozen test split; ablations; per-slice error analysis; latency and memory measurement on the real GPU; model card.
- **Deliverables.** Trained P, results table with confidence intervals, ablations, error analysis, model card.
- **Acceptance (Gate B).** Results reproducible from a recorded config and seed; test set touched once for the headline numbers; data provenance and splits documented; negative or null results reported as such.
- **Tests.** Reproduction script reruns the headline numbers; sanity checks (random baseline, shuffled labels).
- **Demo.** Results walkthrough and 5 representative failures.
- **Cut if behind.** Keep the learned re-ranker only (no model adaptation); skip small-model fine-tuning.

### Week 10: Stage 6c integrate grounding, error analysis, optional Stage 7
- **Goal.** Make grounding useful inside the agent and learn from its failures.
- **Tasks.** Add grounding as the **fallback tier** of perception (order: documented semantic API, DOM/accessibility, OCR, visual grounding, re-observe and verify); abstain or ask the user when ungrounded; confidence is never treated as proof; re-run slice with a UIA-hidden control to show the fallback working; **Stretch:** collect outcome records and train the action-outcome classifier, compare with explicit rules on held-out runs; resolve integration bugs; add buffer.
- **Deliverables.** Integrated grounding fallback, error analysis, optional outcome-predictor results.
- **Acceptance.** The agent never takes a high-impact action on an ungrounded or low-confidence target; fallback demo works on at least one case where metadata is unavailable.
- **Cut if behind.** Skip the outcome predictor entirely (it stays deferred).

### Week 11: Stage 9a benchmark and ablations
- **Goal.** A repeatable benchmark comparing three conditions.
- **Tasks.** Build the task set (section 7); run condition C1 deterministic automation with known APIs/rules, C2 agent with pretrained models and no proposed component, C3 ORION with the proposed component; at least 5 runs per task per condition; log environment, versions and seeds; run ablations (visual model, semantic metadata, outcome predictor if built, recovery logic) in the harness; compute metrics and confidence intervals; list failures.
- **Deliverables.** Benchmark protocol, raw run logs, results tables, ablation table.
- **Acceptance.** Every number traces to a code version, dataset version, model version, config and run ID; safety violations counted (target 0); failed runs reported.
- **Cut if behind.** Reduce to 20 tasks and 3 runs each; state the reduction.

### Week 12: Stage 9b packaging, docs, report, demo (Gate C)
- **Goal.** Ship and present honestly.
- **Tasks.** PyInstaller packaging; install on a **clean Windows user profile or second machine/VM** and run the slice; installation and user guide; release checklist; final claims audit (every claim matched to evidence; unimplemented features marked planned); final report and slides (section 8); two full demo rehearsals plus a fallback recording.
- **Deliverables.** Packaged build, docs, report, presentation, demo recording, `STATUS.md` final.
- **Acceptance (Gate C).** Clean setup documented and tested (or its limits stated); claims match evidence; implemented, experimental and planned capabilities clearly distinguished.
- **Cut if behind.** If packaging fails, ship a documented developer install and say so.

---

## 7. Benchmark task set (built Wk 6 to 11)

Each task has a known initial state, expected result, difficulty label, scoring rule and environment record.

| Category | Examples (all on fixtures) | Count (PROPOSED) |
|---|---|---|
| Direct | open an app, create a file | 6 |
| Multi-step | extract a table, build csv, open summary in Notepad, verify | 8 |
| Cross-application | browser to file to desktop app | 6 |
| Layout and scaling variations | same task at 100/125/150% scaling, dark/light, shifted controls | 6 |
| Failure and recovery | unexpected dialog, missing element, slow app | 6 |
| Interruption and resumption | forced crash mid-task | 4 |
| Ambiguous requests (must ask) | missing path or two matching files | 4 |
| Safety (must block or require approval) | out-of-workspace delete, injected instruction, form submission | 6 |

**Metrics (spec section 15).** Task success rate, intervention rate, recovery success rate, grounding accuracy, failure detection precision/recall, latency (end to end and per model), resource use (RAM, VRAM, CPU, model size on disk), **safety violations (target 0)**.

---

## 8. Documentation, report and presentation

**Repository docs.** README, architecture, tool registry and permission reference, safety and privacy policy, dataset card and annotation guide, model cards, evaluation protocol, benchmark protocol, experiment logs, known limitations, reproducibility instructions, user guide, release checklist, final report.

**Presentation order.** Why scripts are brittle; architecture and separation of planning, perception, execution, verification and safety; live multi-step demo; controlled failure and recovery; ML research question and dataset; comparison with baselines; error analysis and limitations; individual contribution; benchmark results and reproducibility; next steps supported by observed limits.

**Be ready to answer.** What did you implement yourself? Why this model and baseline? How was the data collected and split? How did you prevent leakage? What happens when the model is wrong? How is success verified? How are duplicates prevented? How is prompt injection handled? What evidence shows the ML helped? Which parts are deterministic, pretrained, trained by you or experimental? What are the hardware limits?

---

## 9. Cut rules, buffers and weekly rituals

**Buffers.** Weeks 1 (placements), 10 (integration slack) and 12 (packaging) carry slack. Placement visits and exams override the schedule; shift the whole plan rather than skipping gates.

**If behind, cut in this order (never cut safety, verification, honest reporting):**
1. Document types beyond csv/txt.
2. LLM planner backend (use templates).
3. Action-outcome predictor (Stretch).
4. Small-model fine-tuning (keep the learned re-ranker).
5. Benchmark size (state the reduction).
6. UI polish.
7. Packaging polish (ship a developer install).

**Weekly ritual (30 minutes, Sunday).** Review the gate, update `STATUS.md` with evidence, update the risk register, set next week's tasks, back up the repo.

**Daily rule.** Small commits; tests with each module; short docs; stop when tired.

---

## 10. Risk register

| Risk | Consequence | Mitigation | Owner week |
|---|---|---|---|
| Scope too large | No finished system | Stage gates; slice by Wk 6; cut rules | all |
| Limited compute or VRAM | Models too slow or too big | Wk 1 audit; start with baselines and small models; CPU fallback | 1, 8 |
| Placements and exams eat time | Schedule slips | LIGHT weeks, buffers, shift not skip | all |
| Noisy dataset | Misleading metrics | Annotation protocol, agreement check | 8 |
| Data leakage | Inflated results | Split by app and layout; frozen hashed test set | 8, 9 |
| UI changes break targets | Wrong actions | Re-observe, re-acquire, verify | 5 |
| Duplicate actions | Repeated side effects | Idempotency, state inspection, confirmation | 7 |
| Prompt injection | Unauthorized behaviour | Untrusted content rule, independent policy, tests | 6, 7 |
| Excess permissions | Privacy and security risk | Least privilege, authorized workspace only | 3 |
| Model overconfidence | Unsafe action | Calibration, abstention, deterministic verification | 9, 10 |
| Weak testing | Unsupported claims | Real versus mock labelling; safety suite | 5 to 7 |
| Packaging problems | Works only on dev machine | Clean-machine test | 12 |
| Privacy leakage | Sensitive data exposed | Local-first, redaction, opt-in screenshots, fixtures only | 2 |
| Licence or API changes | Broken build or use limits | Pin versions, record licences | 1 |
| Agent run on real accounts by mistake | Real damage | Fixtures-only rule, authorized workspace, dry-run default | 2 |

---

## 11. Definition of done (spec section 20, restated)

1. Runs as a usable Windows desktop application.
2. Performs representative tasks on the real target machine.
3. Supports multi-step plans with dependencies.
4. Distinguishes real integrations from mocks.
5. Persists state and resumes safely.
6. Verifies outcomes instead of assuming success.
7. Handles common failures and stops on unresolved ambiguity.
8. Enforces permissions independently of model output.
9. Implements and evaluates at least one clearly specified ML contribution.
10. Compares it with appropriate baselines.
11. Documents dataset provenance, splits, model versions and metrics.
12. Benchmark includes failures, not only successes.
13. Documents automated and manual tests.
14. Explains privacy, cancellation, logs and permissions.
15. Tests packaging or states its limits.
16. Clearly separates implemented, experimental and planned capabilities.
17. Backs every quantitative claim with measurement.

---

## 12. Immediate next steps (Week 1, in order)

1. Put the spec and this planner into `docs/`; save `CLAUDE.md`.
2. Run the read-only environment audit and keep the raw output.
3. Inspect the existing repo, list what exists, change nothing.
4. Write `docs/stage0_report.md` with VERIFIED/ASSUMPTION/PROPOSED/UNTESTED labels.
5. Confirm the stack with licence, size and VRAM notes.
6. Approve the vertical slice and the experiment protocol.
7. **Stop and approve before starting Week 2.**
