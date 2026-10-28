# Visual grounding v1: results (2026-10-28)

**Task.** Given a window and an instruction ("the Save button in the toolbar", "Export"), click the right element, or abstain when the target is hidden, missing or ambiguous. A wrong click is the costly error.

**Data.** 600 synthetic pages from `orion.grounding.synth` (6 layout families x 100, randomized theme, font, scale, label language, icon-only buttons), rendered in headless Chromium for exact element boxes, plus page metadata (as UI Automation would give) and local OCR (RapidOCR). Each instruction is evaluated in three phrasings (generator's, "the X button", bare "X"); shorter phrasings become "abstain" when another visible element shares the label.

**Splits.** Families `sidebar_nav` and `wizard` are held out entirely (test). Validation = every 5th seed of the other four families, used only to choose operating points. Fine-tuning used training pages only.

**Operating point (product rule).** Never more wrong clicks than the current rules on validation; within that budget, as many correct answers as possible.

## Results on held-out families (n = 3,960 instructions)

| Method | Correct | Wrong clicks | Gave up | Report |
|---|---|---|---|---|
| B1 metadata only (rules) | 67.8% | 0.9% | 31.3% | grounding_p0_v1.json |
| B2 OCR only (rules) | 48.2% | 10.2% | 41.6% | same |
| B4 metadata + OCR (rules; product before) | 63.1% | 1.0% | 35.9% | same |
| **P0 learned scorer (product now)** | **90.3%** | **0.8%** | 8.8% | same |
| P0 + frozen SigLIP features | 92.5% | 0.8% | 6.7% | grounding_p0_visual_v1.json |
| P1: P0 + LoRA fine-tuned SigLIP | 92.6% | 1.0% | 6.4% | grounding_p1_v1.json (see Correction below) |

P0 vs B4, paired bootstrap 95% CI on the accuracy difference: **+25.8 to +28.7 points**.

**Decisions (as first recorded, 2026-10-28; corrected below).** P0 is in the product. Frozen SigLIP adds about 2 points without fewer wrong clicks; not enabled yet (an 800 MB model at click time). ~~P1 fine-tuning gave no gain over frozen SigLIP and slightly more wrong clicks: not shipped (pre-registered rule; a negative result).~~ Remaining wrong clicks are mostly duplicate labels and ambiguity, which visual similarity does not resolve.

## Correction (2026-10-29): the pre-registered P1 rule had not been applied
The rule fixed before training says: P1 ships only if it beats **P0** on **validation**, with the paired bootstrap 95% CI on the accuracy difference excluding 0. The v1 decision instead compared P1 with *frozen SigLIP* on the *held-out test set*, which is the wrong baseline and the wrong split. `research/training/select_p1.py` now applies the rule as written to the same trained models (no retraining; test numbers for reference only) [`grounding_p1_selection_v1.json`]:

| Comparison | Accuracy difference (95% CI) | Wrong-click difference (95% CI) |
|---|---|---|
| **Validation: P1 - P0 (the rule)** | **+2.2 pts (+0.7 to +3.7)** | -0.1 pts (-0.5 to +0.4) |
| Validation: P1 - P0+frozen SigLIP | +1.6 pts (+0.3 to +2.9) | -0.1 pts (-0.5 to +0.3) |
| Held-out: P1 - P0 | +2.2 pts (+1.3 to +3.3) | +0.1 pts (-0.2 to +0.5) |
| Held-out: P1 - P0+frozen SigLIP | +0.1 pts (-0.7 to +0.9) | +0.2 pts (-0.1 to +0.6) |

**P1 passes the pre-registered rule.** The earlier "negative result" is withdrawn. What remains true: the gain from *fine-tuning* over frozen SigLIP features appears on validation (same layout families) but not on held-out families, so the generalizing part of P1's gain comes from adding SigLIP at all. Whether the product switches to P1 (which needs SigLIP and PyTorch at click time) is an open decision recorded in STATUS.md.

## Conformal abstention (split by page)

| alpha | Coverage, same families | Coverage, held-out families | Mean set size | Act-if-single: correct / wrong |
|---|---|---|---|---|
| 0.10 | 90.7% | 89.4% | 0.70 | 89.8% / 2.6% |
| 0.05 | 95.9% | 96.4% | 0.78 | 94.6% / 2.2% |

Coverage holds in-distribution and approximately on held-out families. As a click rule it gives more wrong clicks than P0's threshold-plus-margin rule (0.8%), so it is not the product's decision rule; it could support "did you mean A or B?" questions.

## Real-world checks
P0 drives `screen.click` in ORION: verified on the canvas demo app (buttons drawn as pixels, invisible to UI Automation) on both the 100% and 125% monitors; refuses a missing button; never confuses "Close Report" with the window's Close button (`tests/end_to_end/test_visual_click.py`).

## Threats to validity
- Synthetic pages from one generator; held-out *families* still share its style. Real-app accuracy is only spot-checked (one demo app).
- An early bug (calibration split alternating phrasings) under-covered; fixed by splitting by page, as reported above.
- Single training seed; no confidence intervals between the visual variants.
