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
| P1: P0 + LoRA fine-tuned SigLIP | 92.6% | 1.0% | 6.4% | grounding_p1_v1.json |

P0 vs B4, paired bootstrap 95% CI on the accuracy difference: **+25.8 to +28.7 points**.

**Decisions.** P0 is in the product. Frozen SigLIP adds about 2 points without fewer wrong clicks; not enabled yet (an 800 MB model at click time). P1 fine-tuning gave no gain over frozen SigLIP and slightly more wrong clicks: **not shipped** (pre-registered rule; a negative result). Remaining wrong clicks are mostly duplicate labels and ambiguity, which visual similarity does not resolve.

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
