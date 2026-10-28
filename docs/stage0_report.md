# ORION Stage 0 Report (Week 1)

**Date:** 2026-10-24 · **Stage:** 0 (environment audit and design) · **Gate status:** awaiting approval

Labels: `VERIFIED` (command run, output quoted here; raw dumps are kept locally, not published (regenerate with `scripts/env_audit.ps1`)), `ASSUMPTION` (believed, not checked), `PROPOSED` (design suggestion), `UNTESTED` (built or planned, not run).

---

## 0. Inputs and repository state

| # | Finding | Label |
|---|---|---|
| 0.1 | `C:\ORION` was **empty** at audit start (recursive listing returned nothing). Nothing existed to preserve. | VERIFIED |
| 0.2 | `C:\ORION` is **not a git repository** (`fatal: not a git repository`). | VERIFIED |
| 0.3 | The project rules (now `docs/PROJECT_RULES.md`), `docs/ORION_Master_Technical_Documentation.md` and `docs/12_WEEK_PLAN.md` **do not exist** on disk. The rules and the 12-week planner were provided as pasted text in chat. **The master spec has not been provided.** | VERIFIED |
| 0.4 | Because the spec is missing, references in this report to "spec section N" come from the planner's citations, not from the spec itself. **Resolved 2026-10-24:** spec copied from the user's Downloads into `docs/` (SHA-256 7BE8E54E…7726, identical to source); see section 10 for the spec-alignment check. | VERIFIED |
| 0.5 | Files created during Stage 0: `scripts/env_audit.ps1` (read-only audit script), `artifacts/env_audit_raw.txt` (its output), `docs/stage0_report.md` (this file). No existing file was modified. | VERIFIED |

---

## 1. Verified findings (machine)

All values come from `scripts/env_audit.ps1` and follow-up read-only commands run on 2026-10-24.

| Area | Finding | Label |
|---|---|---|
| OS | Windows 11 Home Single Language, 10.0.26200, 64-bit | VERIFIED |
| CPU | Intel Core i7-13650HX, 14 cores / 20 threads | VERIFIED |
| RAM | 23.78 GB visible to Windows (24 GB nominal) | VERIFIED |
| Disk | C: 474.7 GB total, **68.1 GB free** | VERIFIED |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, compute capability 8.9 | VERIFIED |
| VRAM | 8188 MiB total; **1899 MiB already in use at idle** by the desktop (Claude, Brave, Edge, VS Code, NVIDIA overlay, Riot Client, etc.), leaving about 6.1 GiB | VERIFIED |
| Driver | NVIDIA 610.88 (Windows driver 32.0.16.1088), WDDM; nvidia-smi reports CUDA UMD 13.3 | VERIFIED |
| CUDA toolkit | `nvcc` not on PATH; `CUDA_PATH` unset (no toolkit installed; not needed for PyTorch wheels) | VERIFIED |
| Displays | Two monitors, both 1920×1080. Monitor at (-1920,0) is at **125%** (120 DPI, the laptop panel, BOE EDID); primary monitor at (0,0) is at **100%** (96 DPI). Measured with a per-monitor-DPI-aware `GetDpiForMonitor` query. | VERIFIED |
| Mixed DPI | A non-DPI-aware process saw the 125% monitor as 1536×864, so **coordinate handling must be per-monitor DPI-aware** from Week 5. | VERIFIED |
| Python | Only one interpreter found: **Python 3.11.9, Microsoft Store build** (`WindowsApps\python.exe`); no `py` launcher | VERIFIED |
| pip | 24.0 | VERIFIED |
| Git | 2.52.0.windows.1 | VERIFIED |
| VS Code | 1.143.0 x64 | VERIFIED |
| Node | v24.13.0 (global packages: kilocode cli, railway cli, localtunnel, typescript; no Playwright) | VERIFIED |
| PyTorch | **torch 2.10.0+cpu**: CPU-only build, `cuda.is_available() == False`. Also installed: pytorch-lightning 2.6.1, torchmetrics 1.8.2, scikit-learn 1.8.0, numpy 2.4.2 | VERIFIED |
| Playwright | Python package **not installed**. A `%LOCALAPPDATA%\ms-playwright` folder exists, holding only a subfolder `b` (dated 10-08-2026); not a usable browser install | VERIFIED |
| pywinauto / uiautomation | **Not installed** | VERIFIED |
| OCR | No Tesseract (not on PATH, not in default install dirs); pytesseract, easyocr and paddleocr not installed | VERIFIED |
| PySide6, Pydantic, pytest | **Not installed** | VERIFIED |

### 1.1 Consequences

- The GPU is usable for ML, but **the current PyTorch cannot use it**. A CUDA-enabled wheel is needed (needs your approval; about 2.5 to 3 GB download). | VERIFIED (fact) / PROPOSED (action)
- About 6 GB of VRAM is realistically free while the desktop is running. Plan for models that fit in about **5 GB at inference** and train only small heads. | PROPOSED
- The Microsoft Store Python works, but it virtualizes `AppData` writes and has quirks with PyInstaller and per-user paths. A project **venv** built from it is the minimum; a python.org 3.11 or 3.12 install is cleaner. | ASSUMPTION (known Store-Python behaviour, not tested here)
- 68 GB free disk is enough for the MVP. It is tight if several grounding models (each several GB) plus datasets are downloaded. Budget is **≤ 25 GB for ORION** (venv, models, data). | PROPOSED

---

## 2. Assumptions

| # | Assumption | How it gets checked |
|---|---|---|
| A1 | Time budget is about 15 to 20 focused hours per week (planner estimate) | Track actual hours in STATUS.md from Week 2 |
| A2 | The laptop stays on AC power during GPU runs; battery mode throttles the 4060 | Check power state in run logs |
| A3 | The CUDA 12.x PyTorch wheels run on driver 610.88 (newer drivers are backward compatible) | Week 2 install plus `torch.cuda.is_available()` |
| A4 | UIA exposes usable trees for Notepad and Calculator on this Windows 11 build (the new Notepad is WinUI-based) | Week 5 real-app test |
| A5 | The licence notes in section 3 are correct as of my knowledge; **not re-checked against the live repos today** | Re-read each LICENSE file at install time |
| A6 | Model VRAM figures in section 3 are approximate (from published sizes, not measured here) | Measure peak VRAM in Week 8 |
| A7 | College exams and placements match the planner's LIGHT weeks | You confirm |
| A8 | No other Python installs exist outside PATH (only PATH and `where` were checked) | Low impact; ignore unless conflicts appear |

---

## 3. Proposed dependency choices (PROPOSED; nothing installed)

| Area | Choice | Licence (ASSUMPTION A5) | Size / VRAM (ASSUMPTION A6) | Why |
|---|---|---|---|---|
| Python | 3.11 venv at `C:\ORION\.venv` | PSF | ~ 100 MB plus packages | Matches the installed interpreter; broadest wheel support |
| Windows UIA | **uiautomation** (primary) plus **pywinauto** (backup, `backend="uia"`) | Apache-2.0 / BSD-3 | < 20 MB, no GPU | uiautomation gives direct access to the UIA tree and patterns; pywinauto has mature app/window helpers |
| Browser | **Playwright (Python)** with Chromium only | Apache-2.0 | ~ 150 to 200 MB browser download | DOM plus accessibility snapshot, auto-wait, isolated throwaway profiles |
| OCR | Bake-off in Week 8 between **Tesseract 5** (Apache-2.0, ~ 80 MB, CPU), **RapidOCR / PaddleOCR ONNX** (Apache-2.0, ~ 15 to 100 MB, CPU/GPU) and **Windows.Media.Ocr** (built into Windows, no install; a free fourth candidate) | as listed | all CPU-capable | UI text is small and anti-aliased; pick on measured accuracy and latency, not reputation |
| PyTorch | **torch with the CUDA 12.x wheel** (for example the `cu126` or `cu128` index), version pinned at install | BSD-3 | ~ 2.5 to 3 GB disk | Matches compute capability 8.9 and the driver |
| Grounding candidates (B3) | Short-list for Week 8: **OmniParser v2** icon detector plus caption (detector AGPL-3.0 because it is YOLO-based; captioner MIT; **licence risk**), **Florence-2-base** (MIT, ~ 0.23 B params, < 2 GB VRAM), **ShowUI-2B** (Apache-2.0 via Qwen2-VL base, ~ 5 to 6 GB in fp16, tight; 4-bit needed), **UI-TARS-2B** (Apache-2.0, similar footprint) | as listed | as listed | Florence-2 is the safest default for 6 GB; a 2B VLM only with quantization |
| Re-ranker (P) | scikit-learn GradientBoosting or LightGBM (MIT) plus logistic calibration | BSD-3 / MIT | CPU | Small data, interpretable features, fast |
| UI shell | PySide6 | LGPL-3.0 (dynamic linking is fine for this project) | ~ 250 MB | Native Qt widgets, global hotkeys via `keyboard`/WinAPI |
| Schemas | Pydantic v2 | MIT | small | Typed tool I/O |
| State | SQLite (stdlib `sqlite3`) | public domain | none | Transactional checkpoints |
| Logging | stdlib `logging` with a JSON formatter (`python-json-logger`, BSD-2) plus a redaction filter | BSD-2 | small | Structured, greppable, no heavy dependency |
| Tests | pytest plus pytest-timeout; markers `mock`, `real`, `safety`, `gpu` | MIT | small | Separates real and mock counts as required |
| Packaging | PyInstaller (GPL-2.0 with bootloader exception, which allows shipping) | GPL+exception | n/a | Week 12 |
| LLM planner (optional) | Local: **Ollama + Qwen2.5-3B/7B-Instruct quantized** (Apache-2.0 for 7B; 3B has its own Qwen licence; check) if VRAM allows **alongside** the grounding model; otherwise template planner only | as listed | 3B Q4 about 2.5 GB, 7B Q4 about 5 GB | 7B plus grounding will **not** fit together in 6 GB; schedule them, or use 3B |

**Licence risk flagged:** OmniParser's detector is AGPL-3.0. Using it inside the shipped agent would put the release under AGPL obligations. Proposed rule: use it **only as a research baseline**, not in the packaged build, unless you accept AGPL. | PROPOSED

---

## 4. Proposed architecture and repository layout

### 4.1 Control loop (PROPOSED)

```
goal ─▶ intent engine ─▶ planner ─▶ plan validator ─▶ task graph (SQLite)
                                                        │
   ┌────────────────────────── per eligible step ───────┴───────────────┐
   │ OBSERVE   perception tiers: semantic API → UIA/DOM → OCR → visual   │
   │ PLAN      choose tool and args (planner or template)                │
   │ AUTHORIZE policy engine (outside the model): allow / confirm / deny │
   │ ACT       executor: timeout, cancel token, idempotency key          │
   │ VERIFY    re-observe; check postconditions with evidence            │
   │ RECOVER   classify error → safe retry / replan / ask / stop         │
   │ CHECKPOINT persist step result + evidence                           │
   └─────────────────────────────────────────────────────────────────────┘
kill switch (hotkey + button) → cancel token checked before every ACT
dry-run mode → executor is replaced by a recorder that executes nothing
```

Invariants (PROPOSED, enforced in code and covered by `tests/safety/`):
1. Only registered tools can run; arguments are validated against Pydantic schemas.
2. Policy decides from the **tool's registered side-effect category**, never from a model-supplied label.
3. A step succeeds only when the verifier reads evidence (file bytes, UIA property, DOM value).
4. Page and document text never enters the instruction channel. It is passed as quoted data with provenance.
5. The cancel token is checked before every action; after cancellation no new action starts.

### 4.2 Repository layout (PROPOSED, as in the planner section 3.1)

```
orion/
  README.md LICENSE pyproject.toml STATUS.md
  docs/        architecture.md safety-and-privacy.md evaluation-protocol.md
               dataset-card-template.md model-card-template.md release-checklist.md
               ORION_Master_Technical_Documentation.md 12_WEEK_PLAN.md stage0_report.md
  src/orion/   app/ interaction/ intent/ planner/ orchestration/ perception/ grounding/
               tools/{windows,browser,files,documents}/ execution/ verification/
               recovery/ policy/ memory/ observability/ models/ config/
  tests/       unit/ integration/ safety/ end_to_end/ fixtures/
  research/    data_collection/ annotations/ baselines/ training/ evaluation/ reports/
  scripts/     env_audit.ps1
  artifacts/   (gitignored except small text reports)
  workspace/   (the ONLY folder ORION tools may write to; gitignored)
```

Added versus the planner: `workspace/` as the explicit authorized output root, and `.gitignore` rules for `artifacts/`, `workspace/`, `*.pt`, `*.onnx`, `*.safetensors` and screenshots. | PROPOSED

---

## 5. First end-to-end vertical slice: "Fixture report" (PROPOSED)

**Task.** From a local fixture page (served from `tests/fixtures/web/`, opened in a throwaway Playwright profile), extract a 5-row table, write `workspace/report.csv` and `workspace/summary.txt` through the bounded file tool, open `summary.txt` in Notepad through UIA, verify the text both on screen (UIA `Document`/`Edit` value) and on disk (bytes), then stop.
**Failure variant.** A pre-existing `summary.txt` triggers a "file exists, overwrite?" decision. A second variant puts a modal dialog over Notepad. ORION must detect it, then ask or recover, and must never overwrite without confirmation.

| ID | Criterion | Target | Measured how |
|---|---|---|---|
| S1 | Clean runs verified successful | ≥ 9/10 | `scripts/run_slice.py --n 10`, log verdicts |
| S2 | Injected-dialog runs: no wrong action / recovered | 10/10 safe; ≥ 7/10 recovered | injection harness |
| S3 | Postconditions read from the result, not inferred | 100% of steps | verifier evidence field non-empty per step |
| S4 | Consequential action without confirmation | 0 | policy audit log |
| S5 | Kill switch stops new actions | ≤ 2 s, 10/10 trials | timestamp of hotkey vs. last action start |
| S6 | Resume after forced kill re-observes and does not repeat uncertain side effects | pass on 5 crash points | crash-injection test |
| S7 | Structured log with step, evidence, verdict | 100% of runs | log schema validation |
| S8 (added) | Slice passes on **both** monitors (100% and 125% DPI) | ≥ 9/10 on each | run with Notepad on each monitor |

S8 is added because mixed DPI was measured in section 1. | PROPOSED

---

## 6. Pre-registered experiment: hybrid UI visual grounding (PROPOSED; to be frozen in Week 8 before any tuning)

> **Revised 2026-10-27 (user-approved, before any freeze).** P is now a fine-tuned SigLIP/CLIP-sized dual encoder scoring hybrid candidates, with split-conformal (and Mondrian) abstention. The feature re-ranker below becomes P0, the baseline and fallback; merged with `docs/proposal_research_depth.md`. The authoritative version is `docs/12_WEEK_PLAN.md` section 5; where they differ, the plan wins.

**Research question.** Does a hybrid candidate-generation plus learned re-ranking approach with calibrated abstention select the correct UI element for a natural-language instruction more reliably than metadata-only, OCR-only and zero-shot pretrained grounding, especially on unseen layout families?

**Task.** Input: screenshot and instruction. Output: box, element class, text, confidence, or ABSTAIN. A prediction is correct if IoU ≥ 0.5 with gold (0.7 also reported). For missing-target items, the correct output is ABSTAIN.

**Data.**
- Synthetic HTML UIs from templates with randomized layout, theme (light/dark), scale (100/125/150%), label vocabulary, duplicates, disabled, hidden and missing targets. Gold labels come from the DOM.
- Safe Windows apps (Notepad, Calculator, Paint, Settings pages without personal info) with manual boxes.
- No personal content. Screenshots are captured on a clean throwaway profile.
- Target: ≥ 1,500 instruction-target pairs; the actual count is reported.

**Annotation.** A written guide covering nested controls, duplicate labels, disabled/hidden elements, missing targets and ambiguity. 15 to 20% double-annotated, with agreement reported as box-IoU agreement plus Cohen's κ on abstain/target. Disagreements are resolved by a written rule. Caveat: as a solo developer, "double annotation" means re-annotation by you after ≥ 1 week, or a volunteer. This weakens the agreement claim and will be **stated as a limitation**.

**Splits.** By application and layout family. ≥ 30% of families held out for test. Near-duplicate check by perceptual hash across splits. Test set frozen and its SHA-256 recorded in `research/reports/test_split.sha256` before any tuning.

**Systems.**
| ID | Method |
|---|---|
| B1 | Accessibility/DOM metadata lookup only |
| B2 | OCR plus exact/fuzzy text match only |
| B3 | Pretrained grounding model, zero-shot (Florence-2 first; a 2B UI-VLM if it fits in VRAM) |
| B4 | Rule-based fusion of B1 to B3 |
| B5 | Simple visual matching (template/feature matching against a reference crop): **required by spec 6.6, missing from the planner and the project rules** |
| P0 | Candidates from B1, B2 and B3 → features (text similarity, role, position, size, visual-embedding similarity, source agreement) → gradient-boosted re-ranker (was P before 2026-10-27) |
| P1 | Same candidates → fine-tuned SigLIP/CLIP-sized scorer (LoRA, listwise loss, hard negatives); ships only if it beats P0 on validation. Temperature scaling + conformal abstention (α = 0.1 primary) apply to the selected one |

**Metrics.** Target-selection accuracy (headline), IoU@0.5 and IoU@0.7, accuracy on unseen families, abstention precision and recall, latency (p50/p95), peak RAM and VRAM. 95% bootstrap CIs (≥ 1,000 resamples) and a paired test of P vs. the best baseline on the same items. Per-slice error analysis (control type, theme, scale, ambiguity).

**Seeds and reproducibility.** Seeds 0, 1, 2 for any stochastic step; mean ± range reported. Every result row records git commit, data version hash, model version and licence, config file and run ID.

**Ablations (harness only).** Remove the metadata, OCR, visual, re-ranker and abstention components one at a time.

**Pre-declared success criterion.** P beats the best baseline on unseen-family accuracy, with a 95% CI on the paired difference that excludes 0. A null or negative result is reported as such.

---

## 7. Risks

| Risk | Severity | Mitigation | Label |
|---|---|---|---|
| **Master spec missing**; the planner and the project rules cite sections that cannot be checked | High | You add `docs/ORION_Master_Technical_Documentation.md`; re-audit this report against it | VERIFIED (risk exists) |
| CPU-only PyTorch installed | Medium | Install the CUDA wheel in the venv in Week 2 (with approval) | VERIFIED |
| ~ 1.9 GB VRAM used by the desktop at idle | Medium | Close GPU-heavy apps (games, Brave hardware accel) during experiments; record free VRAM in each run log | VERIFIED |
| Mixed DPI (100% and 125%) | Medium | Per-monitor DPI-aware process; S8 criterion; record DPI in observations | VERIFIED |
| Microsoft Store Python quirks (path virtualization, PyInstaller) | Medium | Venv now; consider a python.org install before Week 12 | ASSUMPTION |
| Windows 11 Notepad is WinUI and may expose a different UIA tree than classic Notepad | Medium | Real-app test in Week 5; fallback to the fixture Tk app | ASSUMPTION |
| AGPL licence of the OmniParser detector | Medium | Research baseline only; not shipped | ASSUMPTION (licence not re-read today) |
| Solo annotation weakens agreement | Medium | Delayed self-re-annotation, stated limitation | PROPOSED |
| Disk space (68 GB free) | Low to medium | ≤ 25 GB budget; models in one cache dir | VERIFIED (number) |
| Schedule (12 weeks, solo, placements) | High | Gates, cut rules (planner section 9), vertical slice by Week 6 | ASSUMPTION |
| Agent touching real accounts and files | High | `workspace/` only, throwaway browser profile, dry-run default | PROPOSED |
| Prompt injection via fixture or web text | High | Untrusted-data channel, policy outside the model, injection fixture | PROPOSED |

---

## 8. 12-week milestones mapped to stage gates (PROPOSED; from the pasted planner, not from `docs/12_WEEK_PLAN.md`, which does not exist)

| Week | Dates (2026-27) | Stage | Gate / evidence |
|---|---|---|---|
| 1 | 24 to 30 Oct | 0 audit and design | **This report approved** |
| 2 | 31 Oct to 6 Nov | 1 shell, logging, kill switch, dry-run | Kill switch ≤ 2 s on a simulated task; tests green |
| 3 | 7 to 13 Nov | 2 tools, registry, policy | Safety tests: traversal, relabel, deny, timeout, cancel |
| 4 | 14 to 20 Nov | 3 goals, task graph, planner, resume | Invalid plans rejected; crash/resume on fake tools |
| 5 | 21 to 27 Nov | 4a UIA | Real Notepad test (marked `real`) at both DPIs |
| 6 | 28 Nov to 4 Dec | 4b browser plus slice | **Gate A**: S1, S3, S4, S7, injection test |
| 7 | 5 to 11 Dec | 5 recovery and safety | S2, S5, S6 |
| 8 | 12 to 18 Dec | 6a dataset and baselines | Frozen hashed test split; B1 to B4 on validation |
| 9 | 19 to 25 Dec | 6b hybrid P | **Gate B**: test touched once; reproducible |
| 10 | 26 Dec to 1 Jan | 6c integration (plus optional 7) | Grounding fallback demo |
| 11 | 2 to 8 Jan | 9a benchmark | C1/C2/C3 × ≥ 5 runs; safety violations counted |
| 12 | 9 to 15 Jan | 9b release | **Gate C**: clean-profile install; claims audit |

Feasibility note (ASSUMPTION): Weeks 8 and 9 are the most overloaded. Dataset generation, annotation, four baselines and P in two weeks at 15 to 20 h/week is tight. Building the synthetic UI generator can start in Week 7 slack, and the safe-app manual annotation is the first thing to shrink.

---

## 9. Exact next implementation steps (Stage 1; **not started**, need your approval)

Steps needing approval are marked ⚠.

1. Add the missing source docs: you place `docs/ORION_Master_Technical_Documentation.md`; I save the pasted planner as `docs/12_WEEK_PLAN.md` and the pasted instructions as `docs/PROJECT_RULES.md` (new files).
2. ⚠ `git init`, add `.gitignore` (artifacts, workspace, weights, screenshots, .venv), first commit with these docs.
3. ⚠ Create `.venv` from Python 3.11.9; install the Stage 1 set only: `PySide6`, `pydantic`, `python-json-logger`, `pytest`, `pytest-timeout`. Pin versions in `pyproject.toml`. (No torch, Playwright or UIA yet.)
4. ⚠ Separately, when you choose: install the CUDA PyTorch wheel in the venv (~3 GB) and verify `torch.cuda.is_available()` → this resolves A3.
5. Implement in small commits: `config/` loader → `observability/` JSON logger plus redaction filter (with unit tests) → `memory/` SQLite schema (tasks, steps, events) → `orchestration/` cancel token and simulated long task → `app/` PySide6 window (input, task list, log pane, Stop button, global hotkey, dry-run toggle).
6. Stage 1 gate evidence: UI stays responsive during the simulated task; kill switch measured over 10 trials (≤ 2 s); dry-run executes nothing (asserted by test); `STATUS.md` created with evidence.

---

## 10. Addendum (2026-10-24): spec received; alignment check

The spec (`docs/ORION_Master_Technical_Documentation.md`) arrived after this report and Stage 1 were written. Each line below was checked against its text.

### 10.1 Stage 0 items the spec requires that the first audit missed (now done)
Spec section 16, Stage 0, also asks for **permissions** and **installed applications**. Raw output kept locally (contains machine identifiers).

| Finding | Label |
|---|---|
| User `yusuf` is in Administrators, but processes run **non-elevated**; UAC on (`EnableLUA=1`, consent prompt on secure desktop). ORION will run non-elevated and never request elevation (spec 11.3). | VERIFIED |
| Notepad is the **Store/WinUI Notepad 11.2607.14.0**, not classic Notepad; Calculator 11.2607.0.0 and Paint 11.2605.81.0 are present. This raises risk A4 (UIA tree differs from classic Notepad). | VERIFIED (versions) / ASSUMPTION (UIA impact) |
| Browsers: Chrome, Edge, Brave installed; Firefox not. Playwright will use its own bundled Chromium with a throwaway profile, never these browsers' real profiles. | VERIFIED / PROPOSED |
| Microsoft Office folder present (version and licence not checked); LibreOffice absent. Document tools stay file-based (csv/txt/xlsx via Python), not Office automation. | VERIFIED / PROPOSED |

### 10.2 Gaps between the spec and the plan or Stage 1 code
| Spec | Gap | Action | Label |
|---|---|---|---|
| 6.6 baselines | Spec lists **simple visual matching**; planner/project rules omit it | Added as B5 in section 6; planner change needs your approval | PROPOSED |
| 11.6 emergency stop | "Communicate if an operation cannot be interrupted immediately." Stage 1 UI claimed "all tasks stopped" instantly | **Fixed**: label now says "stopping N task(s)…" until threads end; test `test_uninterruptible_action_reported_honestly` | VERIFIED (mock) |
| 9 outcomes | Spec outcomes include **partially complete** and **unverified**; current statuses do not | Add to task-level outcome in Stage 3/4 (verification) | PROPOSED |
| 10 persistence | User controls to **inspect and delete** task history and preferences | Stage 3 (with persistence work) | PROPOSED |
| 4.2, 12 asyncio | Stage 1 runner uses worker threads, not asyncio | Deliberate: Qt plus blocking UIA calls suit threads; revisit when browser (Playwright async) arrives in Stage 4 | PROPOSED |
| 14.5 test status | Use passed / failed / blocked / skipped-with-reason / inconclusive | STATUS.md follows this from now on | PROPOSED |
| 16 Stage 7 / 8 | Outcome prediction (Stretch, Wk 10) and modalities (deferred) | Already in planner; unchanged, not deleted | VERIFIED (planner text) |

Everything else in spec sections 1 to 23 checked against the planner: no capability is removed; deferred items stay listed as deferred.
