# ORION: a verifiable, safety-first autonomous agent for Windows, with hybrid visual grounding

**Draft final report**, generated from the project's evidence on 2026-10-29. Author: Md Yusuf Jawed, B.Tech CSE (AI & ML), final year. [Supervisor, university, date: to fill in.]

Every number below comes from a file in the repository; the source is given in brackets. Placeholders for figures and screenshots are marked **[FIGURE]**.

---

## Abstract

ORION is a desktop agent for Windows that turns a goal ("save the table from sales.html as report.csv, summarize it, and open the summary in Notepad") into a validated plan, carries it out through a fixed set of permissioned tools, checks the result against the real state of the machine, and recovers from common problems. Safety is enforced outside any language model: a policy engine, workspace confinement, confirmations, a kill switch and a dry-run mode apply to every action. On a pre-registered benchmark of 40 tasks in 8 categories, run 5 times each, ORION completed 200 of 200 runs with 0 safety violations; without its recovery engine it completed 40% of the failure-and-recovery runs, and a fixed script making the same calls completed 91% overall [benchmark/REPORT_v1.md].

The research contribution is **hybrid visual grounding**: finding the control a user means from accessibility metadata, local OCR and (optionally) a vision-language model, and abstaining when unsure. A learned feature re-ranker (P0) raised correct answers on held-out synthetic layout families from 63.1% (rule fusion) to 90.3%, with fewer wrong clicks (1.0% to 0.8%; paired bootstrap 95% CI on the gain +25.8 to +28.7 points). A LoRA-fine-tuned SigLIP scorer (P1) passed the pre-registered selection rule against P0 (validation +2.2 points, 95% CI +0.7 to +3.7, wrong clicks unchanged), but its advantage over *frozen* SigLIP features did not hold on held-out families. On real applications the picture changed: with accessibility metadata, rules outperformed the learned scorer (87.5% vs 79.2% correct, both with 0 wrong clicks), and in the end-to-end benchmark the two were equal. The report presents these as they are: a clear gain on synthetic layouts (including unseen families), a fine-tuning benefit that does not generalize beyond its training families, and a measured synthetic-to-real gap.

---

## 1. Introduction

Automation scripts are brittle: they assume a window is where it was, a button has the name it had, nothing pops up in between, and that a command which returned without error did what was intended. Large-model "computer-use" agents promise flexibility, but they move the risk into the model: a wrong guess becomes a wrong click, and prompt text on a web page can become an instruction.

ORION takes the opposite stance. Planning may be flexible, but **every action goes through code that does not trust the planner**: typed tools on an allowlist, a policy engine, confirmation for anything consequential, and verification of the outcome against the machine itself. The core loop is **observe -> plan -> act -> verify -> recover**.

### Objectives
1. A reliable end-to-end agent on Windows across files, a browser (local pages), desktop apps (Notepad, Calculator) and clicking by what is visible.
2. Safety by construction: kill switch, dry run, least privilege, confirmations, workspace confinement, untrusted-content handling, crash-safe resume.
3. One measurable ML contribution: hybrid UI visual grounding with abstention, compared against honest baselines.

### Scope and what was deferred
Voice, webcam and other input modalities, action-outcome prediction and learning from demonstration were deferred (spec roadmap). Clicking by sight is enabled only for an allowlisted demo application; other applications need a safety review first.

---

## 2. System design

**[FIGURE: architecture diagram: UI -> planner -> validator -> graph runner -> tool runtime (registry, policy, confirmer, timeout) -> tools -> verifier; recovery engine; SQLite store; kill switch]**

| Layer | What it does | Key modules |
|---|---|---|
| Interface | PySide6 window: goal box, examples, dry-run toggle (on by default), STOP button, task history, log; confirmation and "which one?" dialogs | `orion.app` |
| Planning | Template planner (deterministic phrases, asks for missing details, refuses unknown requests); optional local LLM planner (own tool-calling loop, constrained decoding, mandatory user review) | `orion.planner` |
| Plan validation | Rejects invented tools, bad arguments, cyclic or dangling dependencies, writes outside the workspace or not named by the user (intent drift), invented file content, denied permissions, user-only arguments; warns about parts it will not do (submit, send, buy) | `orion.planner.validator` |
| Execution | Dependency-ordered graph runner with checkpoints and outcomes; tool runtime validates arguments, checks policy, asks for confirmation, enforces timeouts and cancellation, retries only idempotent tools, flags uncertain outcomes | `orion.orchestration`, `orion.execution` |
| Policy | Allow / confirm / deny from each tool's declared side effect and the granted permissions, outside any model; consequential actions always confirm | `orion.policy` |
| Tools | Files (confined to the workspace; delete goes to a trash folder), app launch, Notepad (UI Automation), Calculator, browser (Playwright, local pages only, throwaway profile, never submits), CSV documents, visual click | `orion.tools` |
| Verification | Read-only checks of the real state (file contents, windows, Notepad text vs disk, click logs); the task outcome is "verified complete" only if they pass, otherwise partial, blocked, failed, cancelled or "unverified" | `orion.verification` |
| Recovery | Classifies a failed step and proposes one safe fix (close a blocking dialog after asking; reselect a lost tab; ask which of two matching buttons), then retries once | `orion.recovery` |
| Memory | SQLite tasks, steps, plans, checkpoints, events; crash-safe resume that never blindly repeats an action with an unknown outcome | `orion.memory` |
| Perception | Per-monitor DPI awareness, window-only capture kept in memory, local OCR (RapidOCR), UI Automation candidates, grounding scorer | `orion.grounding` |

### Safety design
- **Kill switch:** global hotkey (Ctrl+Alt+End) and STOP button; latching; cancels every running task and closes open dialogs. Mock trials: worst case 141 ms to stop, 0 actions started after stop [STATUS.md]. A physical key press was verified; a press *during* a real task (checklist M7) is still a manual check.
- **Dry run** is the default for new tasks.
- **Least privilege:** deleting is not granted by default; when granted it always asks.
- **Untrusted content:** text from web pages and documents is data. The demo page contains an injection string; the plan is fixed before the page is read, and the benchmark confirms nothing else is created [benchmark task S6].
- **Privacy:** ORION reads only the Notepad tab it opened (Windows 11 Notepad restores users' tabs), screenshots are of one window and never saved, logs redact secrets.

---

## 3. Implementation highlights

- **End-to-end slice** (web table -> CSV -> summary -> Notepad, with the Notepad text checked against the file on disk): 10/10 consecutive real runs [STATUS.md, `tests/end_to_end/test_demo_slice.py`].
- **Recovery:** a dialog opened over Notepad mid-task, the active tab switched to another file, two buttons with the same label: each recovered in the benchmark 5/5 [benchmark F1, F3, F5].
- **Crash-safe resume:** the agent process is killed inside a step; on restart a verifiable step is verified rather than repeated, an unverifiable one is marked for review and **not** repeated, a read-only one is re-run [`tests/integration/test_graph_runner.py`, benchmark I1-I3].
- **Packaging:** a portable PyInstaller build (220 MB zip). On a new standard Windows user with no Python and no browser, the built app's self-test passed 5/6 (browser missing, with the fix shown), `--install-browser` downloaded Chromium in 26 s, then 6/6; the packaged window completed a visual-click task [artifacts/acceptance_clean_profile.json].
- **Tests:** 253 automated tests without the desktop and 20 on the real desktop pass [STATUS.md].

**[FIGURE: screenshot of the main window during the end-to-end demo]** **[FIGURE: the "which one did you mean?" dialog]**

---

## 4. Research: hybrid visual grounding

### 4.1 Question and task
Given a window and an instruction ("the Save button in the toolbar", "Export"), choose the element to click, or **abstain** when the target is missing, hidden or ambiguous. A wrong click is the costly error, so every method is compared on correct answers **and** wrong clicks.

### 4.2 Data and splits
600 synthetic pages from ORION's own generator (6 layout families x 100; random themes, fonts, scale, label language, icon-only buttons), rendered in Chromium for exact element boxes, with accessibility-style metadata and local OCR. Each instruction is evaluated in three phrasings; shorter phrasings become "abstain" when another visible element shares the label. **Two families (sidebar navigation and wizard) are held out entirely as the test set**; validation is every fifth seed of the other four families and is used only to choose operating points [research/reports/grounding_v1.md].

*Deviation from the plan:* the plan targeted at least 10,000 synthetic pairs and 500 hand-annotated real pairs with double annotation. The real-app set (Section 4.6) is labelled automatically from UI Automation instead, and no inter-annotator agreement was measured.

### 4.3 Methods
- **Metadata only (rules)**, **OCR only (rules)**, **metadata + OCR rule fusion** (text similarity, role, source agreement; threshold and ambiguity margin).
- **P0:** gradient-boosted re-ranker (scikit-learn) over 20 hand-designed features of the same candidates (text similarity, exact match, role, source, OCR confidence, duplicate counts, container-heading distance, position), with a probability threshold and ambiguity margin chosen on validation under the rule "never more wrong clicks than the rules".
- **P0 + frozen SigLIP:** image-text similarity of each candidate crop and the target text (google/siglip-base-patch16-224, Apache-2.0) as two extra features.
- **P1:** the same with SigLIP fine-tuned by LoRA (rank 8, query/value projections) with a listwise multi-positive loss on training families only.
- **Selection rule (pre-registered):** P1 ships only if it beats P0 on validation with a bootstrap CI excluding zero; otherwise P0 ships and P1 is reported as a negative result.
- **Conformal abstention:** split conformal prediction sets (split by page), as an analysis and as a possible "did you mean" source.

*Not run:* the plan's simple visual-matching baseline and a standalone zero-shot visual grounding model; pretrained vision features enter only through P0 + frozen SigLIP.

### 4.4 Results on held-out families (n = 3,960 instructions)

| Method | Correct | Wrong clicks | Abstained |
|---|---|---|---|
| Metadata only (rules) | 67.8% | 0.9% | 31.3% |
| OCR only (rules) | 48.2% | 10.2% | 41.6% |
| Metadata + OCR (rules) | 63.1% | 1.0% | 35.9% |
| **P0 learned re-ranker (shipped)** | **90.3%** | **0.8%** | 8.8% |
| P0 + frozen SigLIP | 92.5% | 0.8% | 6.7% |
| P1 LoRA-fine-tuned SigLIP | 92.6% | 1.0% | 6.4% |

P0 vs rule fusion: paired bootstrap 95% CI on the accuracy difference **+25.8 to +28.7 points** [grounding_v1.md]. Frozen SigLIP adds about 2 points with no fewer wrong clicks, at the cost of an 800 MB model at click time, so it is not enabled. The remaining errors are mostly duplicate labels and ambiguity, which visual similarity does not resolve.

**Selection rule for P1 (applied as pre-registered, on validation)** [grounding_p1_selection_v1.json]:

| Comparison | Accuracy difference (95% CI) | Wrong-click difference (95% CI) |
|---|---|---|
| Validation: P1 - P0 (the rule) | **+2.2 (+0.7 to +3.7)** | -0.1 (-0.5 to +0.4) |
| Validation: P1 - P0 + frozen SigLIP | +1.6 (+0.3 to +2.9) | -0.1 (-0.5 to +0.3) |
| Held-out: P1 - P0 | +2.2 (+1.3 to +3.3) | +0.1 (-0.2 to +0.5) |
| Held-out: P1 - P0 + frozen SigLIP | +0.1 (-0.7 to +0.9) | +0.2 (-0.1 to +0.6) |

P1 passes the rule. The benefit of *fine-tuning* over frozen features appears only on the training families' validation split, not on unseen families. **Process note:** the first write-up compared P1 with frozen SigLIP on the test set and wrongly called it a negative result; the rule was then applied as written to the same trained models and the conclusion corrected (grounding_v1.md, "Correction"). [Decision on shipping P1 in the product: to fill in.]

### 4.5 Conformal abstention

| alpha | Coverage, training families | Coverage, held-out families | Mean set size | Act only on single-element sets: correct / wrong |
|---|---|---|---|---|
| 0.10 | 90.7% | 89.4% | 0.70 | 89.8% / 2.6% |
| 0.05 | 95.9% | 96.4% | 0.78 | 94.6% / 2.2% |

Coverage holds in-distribution and approximately on unseen families. Used as a click rule, it allows more wrong clicks than P0's threshold-and-margin rule, so it is not the product's decision rule. An early version under-covered because calibration and test shared pages across phrasings; splitting by page fixed it [grounding_v1.md].

### 4.6 Synthetic-to-real: real Windows applications
ORION's own blank windows of Calculator and Paint (two window sizes each) and, in the second run, Character Map; every enabled, named, clickable control is a target; nothing is clicked [research/reports/grounding_real_v1.md].

- **First run (n = 275):** with metadata, the learned scorer was correct on 58.5%, rules on 84.7%, **both with 0 wrong clicks**. Diagnosis: real applications expose one control as several nested accessibility elements with the same name (a menu item and a button with the same box plus a text label), which the scorer read as duplicate labels. The synthetic generator never produces this.
- **Fix:** fold nested same-name elements into one candidate. **Second run (n = 240):** learned 79.2%, rules 87.5%, still 0 wrong clicks. This fix was designed after seeing the first run, so the second run is not a clean held-out result on Calculator and Paint; Character Map (8 controls) was the only unseen application.
- **Reading alone is not enough:** with OCR only, about 10% of real controls are found, because most are icons; the wrong clicks in this condition were on captions printed under icon buttons.

### 4.7 What the research shows
1. A cheap learned re-ranker over hybrid candidates substantially improves grounding **in distribution and on held-out synthetic layout families**, while lowering wrong clicks.
2. Adding a vision-language model's image-text similarity helps, and the fine-tuned version passes the pre-registered rule against P0; but fine-tuning's extra gain over frozen features did not generalize to unseen layout families.
3. The gain **did not transfer** to real applications with accessibility metadata, where exact-match rules are strong; the main causes (nested elements, near-identical long labels) are now known and specific.
4. End to end, on the benchmark's visual tasks, the learned scorer and the rules were equal (50/50 each) [benchmark C2 vs C3]. There is therefore **no end-to-end evidence yet that the learned scorer improves the product**.

---

## 5. Local LLM planner (C4)

ORION's own tool-calling loop with Phi-3.5-mini (3.8B, 4-bit, local via Ollama on the laptop GPU, 3.8 GB VRAM) was measured on 24 frozen prompts (plan / ask / refuse / reject) [research/reports/c4_planner_eval_v1.md]:
- Constrained decoding is required: without it, 0 of 24 replies were usable.
- After fixing a schema bug in ORION and a prompt iteration judged only on a separate development set: behaviour 8/24 (template 24/24, on prompts written alongside it), safe rate 12/12, exact plan match 4/12. On paraphrases the template cannot parse, the LLM completed 6/8 vs 3/8.
- Before the intent-drift check, the LLM silently rewrote `..\escape.txt` to `escape.txt` and invented a destination; the validator now rejects both. It cannot catch invented content, so every LLM plan is shown to the user before it runs.
- Verdict: an opt-in helper for paraphrased requests, not the default planner.

---

## 6. Benchmark

### 6.1 Protocol
Pre-registered and committed before the run [benchmark/PROTOCOL.md]: 40 tasks in 8 categories (direct, multi-step, cross-application, layout and scaling on the 100% and 125% monitors with light/dark and shuffled layouts, failure and recovery, interruption, ambiguous requests, safety); 5 runs per task per condition; fresh temporary workspace per run; **pass/fail decided by independent checks of the world** (files on disk, the demo app's click log, the form's state over CDP), not by ORION's verifier.

Conditions: **C3** ORION as shipped; **C2** ORION with rule grounding instead of the learned scorer (visual tasks only); **C1** a fixed script making the same tool calls with no planning, validation, verification or recovery (still through ORION's runtime); **A_norec** ORION without the recovery engine (failure tasks only).

### 6.2 Results (435 runs, about 20 minutes)

| Condition | Success (95% Wilson CI) | Safety violations |
|---|---|---|
| **C3 ORION** | **200/200, 100% (98-100)** | **0** |
| C2 rule grounding | 50/50, 100% (93-100) | 0 |
| C1 fixed script | 145/160, 91% (85-94) | 0 |
| A_norec without recovery | 10/25, 40% (23-59) | 0 |

- **Recovery is what makes ORION robust:** dialog, lost tab and two-matching-buttons tasks pass 5/5 with ORION and 0/5 without recovery or as a script. Without recovery ORION still stopped safely and flagged all 15 failures; it never claimed success when the checker disagreed (0 false "complete" claims in all conditions).
- **Safety does not depend on the planner:** all safety runs pass in every condition, including the plain script, because confinement, permissions and confirmation live in the runtime.
- **Honest outcomes:** in 25 runs ORION reported "unverified" because it had no check for the result (reading, listing, Calculator, form fill); all had in fact succeeded.
- **Cost:** median 0.75 s per task (p95 7.8 s); peak 530 MB RAM; about 2 CPU cores during OCR; no GPU at run time; grounding model 1 MB.

Disclosed changes after the run: the failure-detection metric first counted "unverified" as a false alarm and was corrected on the same raw runs; the "fill and submit" task revealed that ORION dropped "submit" silently, and the validator now tells the user (not re-benchmarked).

---

## 7. Discussion

### What worked
Putting policy, confinement and verification in code outside the planner. It made the system safe even when the planner was weak (C4) or absent (C1), and it made failures visible rather than silent. Recovery turned the most common real-world disruptions from hard failures into completed tasks.

### What did not
The learned grounding gain did not carry over to real applications, and fine-tuning a vision-language model added nothing over its frozen features on unseen layout families. The small local LLM was not good enough to plan unaided. A process failure is also worth reporting: the P1 decision was first made on the wrong comparison and split, and was corrected only when the pre-registered rule was re-checked for this report.

### Threats to validity and limitations
- The benchmark tasks are within the template planner's phrases, and the fixtures were built by the same author as ORION: 100% shows reliability on known task types, not general ability.
- Synthetic grounding data comes from one generator; held-out *families* still share its style. Real-app evaluation covers three applications on one machine and is auto-labelled.
- Single training seed for the grounding models; confidence intervals only where stated.
- Display scaling is covered by two monitors (100%, 125%), not by changing Windows scaling; slow-application timeouts are not benchmarked.
- Manual checks M7 (kill-switch key press during a running task) and M9 (visual crispness at 125%) remain open.

---

## 8. Individual contribution

| Component | Origin |
|---|---|
| Agent architecture, planner(s), plan validator, policy engine, tool runtime, all tools, verifier, recovery engine, graph runner, crash-safe resume, UI, packaging, self-test | written for this project |
| Synthetic UI generator, rendering pipeline, features, P0 training, operating-point selection, conformal analysis, fine-tuning objective and loop, real-app evaluation, benchmark harness and protocol | written for this project |
| SigLIP base weights (Apache-2.0), Phi-3.5-mini (MIT), RapidOCR models (Apache-2.0), PySide6, Playwright, uiautomation, scikit-learn, PyTorch, PEFT | third-party, used and acknowledged; no third-party model was trained from scratch |

Development was assisted by an AI coding assistant (Claude Code); design decisions, approvals at each stage gate, manual checks and the clean-profile test account were the author's. [Adjust to your institution's disclosure rules.]

---

## 9. Conclusion and future work

ORION shows that a Windows agent can be reliable and safe on its supported tasks by verifying outcomes and enforcing policy outside the planner: 200/200 benchmark runs with no safety violations, and robust recovery from the disruptions that break scripts. The grounding research gave a clear improvement on synthetic layouts (including unseen families), a fine-tuned scorer that passes its pre-registered rule but whose fine-tuning benefit does not generalize, and a measured synthetic-to-real gap with identified causes.

Next steps supported by these results: (1) a hand-annotated real-application grounding set and a generator that produces nested accessibility trees and near-identical labels; (2) choose between learned and rule grounding per source on a real validation set; (3) let task outcomes use tools' own checks (Calculator, form fill) instead of "unverified"; (4) a stronger local planner model with plan review; (5) code signing and a second-machine install.

---

## Appendix A: Reproducing the results

| Result | Command | Evidence |
|---|---|---|
| Tests | `pytest -m "not real"` (offscreen), `pytest -m real` | STATUS.md |
| Grounding v1 | `research/data_collection/render_synth.py`, `research/training/train_grounding.py` (+ `--visual`), `embed_siglip.py`, `finetune_siglip.py` | `research/reports/grounding_*_v1.json` |
| Real-app grounding | `research/eval_real/eval_real_apps.py` | `research/reports/grounding_real_v{1,2}.json` |
| LLM planner | `scripts/eval_planner.py` | `research/planner_eval/` |
| Benchmark | `python -m benchmark.run_benchmark --runs 5` | `benchmark/results/20261028-220054/` |
| Release | `packaging/build.ps1`; `ORION.exe --selftest` | `docs/RELEASE_CHECKLIST.md`, `artifacts/acceptance_clean_profile.json` |

Hardware: Intel i7-13650HX, 23.8 GB RAM, NVIDIA RTX 4060 Laptop (8 GB), Windows 11 Home, displays 1920x1080 at 100% and 125%.

## Appendix B: Short answers to likely viva questions
- **What did you implement yourself?** Section 8.
- **How is success verified?** By read-only checks of the real state after each step and at the end; "verified complete" only if they pass. The benchmark used separate, independent checks.
- **What happens when the model is wrong?** The validator rejects plans that leave the workspace, invent destinations or content, or use denied tools; LLM plans need user approval; grounding abstains or asks "which one?" instead of guessing; a wrong outcome is caught by verification and reported.
- **How are duplicate actions prevented?** Idempotency flags (only idempotent tools are retried), action ids recorded before each step, and resume never repeats a step whose outcome is unknown.
- **How is prompt injection handled?** Page and document text is returned as data; plans are fixed before content is read; no tool sends or submits anything.
- **What evidence shows the ML helped?** In distribution and on held-out synthetic families, strongly (+27 points, CI excludes zero). On real apps and end to end, not yet; that is reported as a finding.
- **Which parts are deterministic, pretrained, trained by you, experimental?** Deterministic: planner (default), validator, policy, tools, verifier, recovery. Pretrained: OCR models, SigLIP, Phi-3.5. Trained by the author: P0 re-ranker, P1 adapter. Experimental: LLM planner (opt-in), SigLIP features and P1 (not in the product), conformal sets (analysis).
- **Did you ever get a result wrong?** Yes: the P1 decision was first made on the test set against the wrong baseline. Re-applying the pre-registered rule reversed it; both versions are documented.
- **Hardware limits?** The agent itself needs no GPU (530 MB RAM peak); the LLM planner needs about 3.8 GB VRAM; SigLIP at click time would add about 800 MB.
