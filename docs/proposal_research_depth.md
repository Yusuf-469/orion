# Proposal: deepening ORION's research core

**Status:** PROPOSED. Not approved. Changes nothing until approved.
**Date:** 2026-10-25.
**Affects (if approved):** `docs/12_WEEK_PLAN.md` section 5 and Weeks 4 to 10; Stage 6 and Stage 3 scope. The spec and the planner stay authoritative until they are edited. This file only proposes.

> Evidence labels follow `CLAUDE.md`: VERIFIED, ASSUMPTION, PROPOSED, UNTESTED. Everything here is PROPOSED unless marked otherwise. No numbers in this file are results.

---

## 1. Why change anything

The current plan for the proposed method P (planner section 5) is a gradient-boosted or logistic re-ranker over hand-made features, with model adaptation as an optional stretch. It is valid and cheap, but the parts that are technically hardest (planner LLM, pretrained grounding model) would be someone else's models. An examiner or interviewer can reasonably say "this is pretrained models plus a classifier."

Spec section 7 already sets the bar: "A pretrained model integration can be valuable engineering, but is not by itself evidence of original research." This proposal makes the part ORION trains itself the centre of the project, and keeps the current re-ranker as a baseline and fallback.

Spec 7.1 step 7 says "adapt or fine-tune only when justified". Section 3.5 defines that justification as a pre-registered rule, so the fine-tuned model is used only if it beats the re-ranker on validation.

## 2. Summary of proposed changes

| # | Change | Replaces or extends | Stage | Priority |
|---|---|---|---|---|
| C1 | Fine-tune a small vision-text scorer (LoRA, contrastive, hard negatives) as the proposed method | Extends P; the current re-ranker becomes baseline P0 | 6b | Core |
| C2 | Treat the synthetic UI generator as a research instrument: randomization ablations and a measured synthetic-to-real gap | Extends 6a dataset work; adds a research question | 6a, started earlier | Core |
| C3 | Calibration plus split conformal prediction for abstention, with risk-coverage curves | Replaces "calibrated abstention" with a defined method | 6b/6c | Core |
| C4 | Own tool-calling loop for the LLM planner with schema-constrained output; measure invalid-call rate | Extends the Week 4 planner | 3 | Supporting |
| C5 | Learned before/after-screenshot outcome verifier | Upgrades the Stage 7 stretch | 7 | Stretch |

Unchanged: the safety architecture, the policy engine outside the model, baselines B1 to B5, the leakage rules, the frozen test split, reporting rules and every stage gate.

## 3. C1: fine-tuned grounding scorer

### 3.1 Task (unchanged from planner section 5)
Input: screenshot and instruction. Output: target box, class, text and score, or **abstain**. Correct if IoU ≥ 0.5 (also report 0.7).

### 3.2 Two-stage design
1. **Candidate generation (deterministic, existing plan):** UIA/DOM elements, OCR boxes and the B3 detector's boxes, merged and de-duplicated.
2. **Scoring (learned, new):** for each candidate, score how well it matches the instruction. The highest score wins unless C3 says to abstain.

Why two stages: candidate generation keeps the search space small and grounded in real elements, and the learned part does what rules cannot (matching icons, resolving duplicate labels, using context). It also lets the scorer run on a 6 GB GPU, because it scores crops instead of generating boxes over the whole screen.

### 3.3 Model (PROPOSED; licences and VRAM UNTESTED)
- **Backbone:** a small pretrained image-text encoder. Candidates: SigLIP-base (ASSUMPTION: Apache-2.0, about 0.2 B parameters) or the Florence-2-base vision encoder (MIT per `stage0_report.md`). Pick by licence check and a VRAM measurement in Week 8.
- **Inputs per candidate:** crop of the element plus surrounding context, OCR or metadata text, and normalized position and size features.
- **Head:** a small fusion MLP over the image embedding, the instruction embedding and the structured features, producing one score per candidate.
- **Adaptation:** LoRA on the encoders' attention layers. The backbone stays frozen otherwise. Mixed precision.
- **Budget (ASSUMPTION, to measure):** fits in about 6 GB free VRAM at batch sizes useful for contrastive training. If not, fall back to frozen encoders and train only the fusion head.

### 3.4 Training objective
- **Loss:** listwise softmax cross-entropy over the candidate set for each instruction (the correct candidate against all others on the same screen), in the InfoNCE style.
- **Hard negatives** (logged per batch, so ablations are possible): same text with a different role; same role with similar text; duplicate labels in different containers; disabled or hidden copies of the target; spatial neighbours.
- **Missing-target examples:** screens where the instruction has no valid target. These are used by C3 to evaluate abstention, not as training positives.
- **Hyperparameter tuning** on the validation split only. One final run on the frozen test split.

### 3.5 Pre-registered selection rule
- **P0** = the current gradient-boosted or logistic re-ranker (kept exactly as specified in planner section 5).
- **P1** = the C1 fine-tuned scorer.
- P1 becomes ORION's grounding method only if it beats P0 on validation target-selection rate, with a bootstrap 95% CI on the difference that excludes 0. Otherwise P0 ships and P1 is reported as a negative result. Both are reported on the test split either way.

### 3.6 What this adds to the defence
The training objective, the negative-sampling design, LoRA and the fusion architecture are ORION's own work. The pretrained backbone is acknowledged as pretrained.

## 4. C2: synthetic data engine as a research instrument

### 4.1 Second research question
> How much of the synthetic-to-real gap in UI grounding is closed by each randomization factor (layout, theme, font, scaling, label language, icon style)?

### 4.2 Design
- **Generator:** HTML templates rendered with Playwright, with labels taken from the DOM (already planned). Each randomization factor gets an on/off switch and a seeded config.
- **Real evaluation set:** hand-annotated screenshots of safe Windows apps (Notepad, Calculator, Paint, Settings without personal data), using the existing annotation protocol and agreement measurement.
- **Experiment:** train P1 on synthetic data with all factors on, then with each factor removed (leave-one-out). Evaluate every model on the same frozen real set. Report the target-selection rate with CIs for each configuration.
- **Leakage:** the real set is never used for training or tuning. Synthetic test layout families are held out as already required.

### 4.3 Scheduling change
The generator moves earlier: a minimal version in Weeks 4 to 7, at about 3 hours a week alongside Stages 3 to 5 (ASSUMPTION: fits the 15 to 20 hour budget). Week 8 is then for annotation, baselines and freezing the splits, not for building the generator from scratch.

## 5. C3: calibrated abstention with conformal prediction

### 5.1 Method
1. **Temperature scaling** of the scorer's softmax on a calibration split, which is held out from training and comes from the training layout families. Report ECE before and after.
2. **Split conformal prediction:** compute a score threshold on the calibration split so that, for user-chosen α (for example 0.05), the selected candidate is wrong at most α of the time **under exchangeability**.
3. **Decision rule:** act only if the top candidate's calibrated score clears the threshold **and** the conformal prediction set contains a single candidate. Otherwise abstain: re-observe, then ask the user.

### 5.2 Honest limitation (must appear in the report)
The conformal guarantee holds only when test data is exchangeable with calibration data. Held-out layout families and real apps are a distribution shift, so the guarantee does **not** automatically transfer there. The report must show empirical error and coverage on (a) in-distribution synthetic data, (b) held-out synthetic layouts and (c) real apps, and state where the guarantee held and where it failed.

### 5.3 Metrics added
- Risk-coverage curves: error rate against the fraction of instructions answered.
- Empirical error rate at α = 0.05 and 0.10, per split.
- Abstention precision and recall on missing or ambiguous targets (already in the planner).

### 5.4 Safety link (unchanged rules)
A calibrated score is still not proof. Postcondition verification and confirmation of consequential actions stay mandatory whatever the score.

## 6. C4: own tool-calling loop (Stage 3)

- The LLM backend outputs a tool call as JSON. ORION validates it with the existing Pydantic tool schemas before the policy engine sees it.
- Where the local runtime supports it, decoding is constrained to the tool-call JSON schema (ASSUMPTION: Ollama structured outputs support this; verify in Week 4).
- **Measured on the fixed prompt set:** plan validation rate and invalid-tool-call rate, with and without constrained decoding, and for the template planner as a baseline.
- No agent framework (LangChain or similar). The loop is ORION code, which keeps policy enforcement visible and testable.

## 7. C5: learned outcome verifier (stretch, Stage 7)

- **Input:** before and after screenshots of the target region plus the existing structured outcome features.
- **Model:** a small CNN or the C1 backbone's frozen image features with a classification head.
- **Labels:** verified success, confirmed failure, unexpected transition, inconclusive (unchanged).
- **Compared against:** explicit rules and the planner's logistic or decision-tree baseline, on held-out runs.
- It never replaces postcondition verification and never authorizes a consequential action (unchanged).

## 8. Updated baseline and method table (proposed replacement for planner section 5)

| ID | Method |
|---|---|
| B1 | Accessibility or DOM metadata lookup only |
| B2 | OCR plus exact or fuzzy text matching only |
| B3 | Pretrained grounding or detection model, zero-shot |
| B4 | Rule-based fusion of B1 to B3 |
| B5 | OpenCV template or feature matching |
| P0 | Gradient-boosted or logistic re-ranker over candidates (current P) |
| P1 | Fine-tuned contrastive vision-text scorer over candidates (C1) |
| +C3 | Calibration and conformal abstention applied to the selected method |

**Ablations (harness only):** remove metadata features, OCR text, visual features, hard negatives, LoRA (frozen backbone), each randomization factor (C2), and abstention.

## 9. Cut rules (in priority order, if behind)
1. Drop C5.
2. Drop constrained decoding in C4; keep schema validation and the invalid-call metric.
3. In C1, freeze the backbone and train only the fusion head (no LoRA).
4. In C2, reduce leave-one-out to the three factors with the largest expected effect (layout, theme, scaling).
5. If C1 cannot train at all: ship P0 with C3. That is still stronger than the current plan because of the conformal abstention analysis.

Never cut: the frozen test split, the real-app evaluation set, honest reporting of where the conformal guarantee fails, or any safety rule.

## 10. Dependencies and approvals needed
All of these need explicit approval under `CLAUDE.md`. None are installed by this proposal.
- CUDA PyTorch wheel in the venv (already pending in `STATUS.md`; about 2.5 to 3 GB).
- `transformers` and `peft` for the backbone and LoRA (ASSUMPTION: both Apache-2.0; verify).
- Backbone weights download (size and licence to verify in Week 8).
- Playwright (already planned for Stage 4).

## 11. Pitch line if approved
"ORION is a safety-first Windows computer-use agent. Its core is a grounding model I trained on synthetic interfaces, with a measured synthetic-to-real gap and conformal guarantees on when the agent is allowed to act, and an honest account of where those guarantees break."

## 12. Decision requested
Approve, modify or reject C1 to C5 individually. If approved, the next step is to edit `docs/12_WEEK_PLAN.md` section 5 and Weeks 4 to 10, and to add rows to `STATUS.md`. Each of those edits needs separate approval because they change existing files.
