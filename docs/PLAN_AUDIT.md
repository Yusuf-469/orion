# 12-week plan audit (2026-10-29)

Each planned item from `docs/12_WEEK_PLAN.md` checked against the repository. **Done** = evidence exists (STATUS.md / reports / tests). **Partial** = built in a narrower form. **Missing** = not done. **Cut** = dropped under the plan's own cut rules or deferred by design.

## Summary
| Week / stage | Verdict | Main gaps |
|---|---|---|
| 1 Stage 0 audit and design | Done | |
| 2 Stage 1 shell, kill switch, dry run | Done | human checks M7 (key press during a running task), M9 (crispness at 125%) |
| 3 Stage 2 tools, registry, policy | Done | |
| 4 Stage 3 planner, validator, resume, LLM loop (C4) | Done | graph tests are example-based, not property-based |
| 5 Stage 4a Windows UI Automation | Partial | no generic UIA action tools (focus/click/type/key/wait on any control) and no normalized observation schema; ORION has app-specific tools (Notepad, Calculator) instead |
| 6 Stage 4b browser, first slice (Gate A) | Done (with cuts) | xlsx cut to csv (allowed by the cut rule); no generic browser click/wait/screenshot tools; no screen recording of the slice |
| 7 Stage 5 recovery, safety | Mostly done | no replanning (one fix + one retry); stale element, slow app and closed window are not injected (cut rule allows dialog, missing element, timeout, crash) |
| 8 Stage 6a dataset, baselines, frozen splits | **Partial (largest gap)** | no written annotation protocol, annotation tool, double annotation or agreement; no 500 hand-annotated real pairs (real set is auto-labelled from UIA); no B3 (zero-shot pretrained detector) or B5 (OpenCV visual matching); no OCR bake-off; no dataset card; no split-leakage test or metric toy tests; test set not frozen as a hashed artifact before tuning |
| 9 Stage 6b P0/P1, calibration (Gate B) | **Partial** | single seed (plan: 0/1/2); no explicit hard-negative mining or fusion MLP (P1 = fine-tuned SigLIP similarity as a feature in P0); no temperature scaling / ECE, no Mondrian conformal, no risk-coverage curves; **second research question (synthetic-to-real leave-one-factor-out) not run**; IoU@0.5/0.7 not reported (centre-in-box used); planned ablations mostly not run; no model card; no reproduction script or sanity checks (random baseline, shuffled labels); test split evaluated for several variants, and the P1 decision first used it (corrected) |
| 10 Stage 6c integration, Stage 7 | Partial | grounding is used by `screen.click` only (allowlisted demo app), not as a general fallback tier; learned outcome verifier (stretch) not built, so deferred |
| 11 Stage 9a benchmark | Done | 40 tasks vs 46 planned (all 8 categories covered); no semantic-metadata ablation in the benchmark; development-workflow scenario (stretch) not built; 150% scaling not covered |
| 12 Stage 9b release (Gate C) | Mostly done | slides, two rehearsals and a fallback recording (author); licence notices in the zip; code signing |

## Done well beyond the plan's minimum
Recovery "which one?" dialog, clean-profile install test with a real browser download, benchmark with independent checkers and 5 runs (plan's cut allowed 3), real-app grounding evaluation with a found-and-fixed bug, own LLM tool-calling loop with two evaluation iterations.

## Capability register (section 2)
- MVP subsystems 1-12: all present; perception (4) is narrower than planned (see Week 5).
- Deferred by design and still deferred: speech, webcam, USB/assistive devices, demonstration learning.
- Stretch not built, therefore deferred: learned action-outcome prediction, development-workflow scenario.
- Repository layout: missing `LICENSE`, `docs/model-card-template.md`, `docs/dataset-card-template.md`, `docs/evaluation-protocol.md` (the benchmark has `benchmark/PROTOCOL.md`), `research/annotations|baselines|evaluation/` (work lives in `research/training`, `research/eval_real`).

## Gaps by cost to close
- **Cheap, no new data (about an hour each):** model card and dataset card; split-leakage test and metric toy tests; temperature scaling + ECE and risk-coverage curves from existing scores; sanity checks (random baseline, shuffled labels); P0 seeds 1 and 2; IoU@0.5/0.7 alongside centre-in-box.
- **Moderate (a few hours, mostly compute):** B5 OpenCV template matching; P1 seeds 1 and 2 (GPU); synthetic-to-real leave-one-factor-out (regenerate data per factor, retrain P0, evaluate on the real-app set).
- **Needs the author:** hand annotation of real-app pairs with a second annotator; choosing a licence for `LICENSE`; B3 needs a pretrained detector download (licence and size check first); slides, rehearsals, recording.
