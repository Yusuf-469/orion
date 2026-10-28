# Visual grounding on real Windows apps (2026-10-28)

**Question.** The grounding scorer was trained only on synthetic pages. Does it find controls in real apps?

**Protocol** (fixed in `research/eval_real/eval_real_apps.py` before the first run): ORION's own new windows of Calculator and Paint (blank), plus Character Map in v2 only; two window sizes for Calculator and Paint. The answer key is UI Automation: every enabled, on-screen, named clickable control. The instruction is the control's name. **Correct** = the point ORION would click lies inside that control; **wrong** = anywhere else, or any click when two separate controls share the name. Nothing was clicked; screenshots stayed in memory; no personal content was on screen (ORION's window was kept on top and checked to be fully visible).

## v1: as trained (`grounding_real_v1.json`, n = 275)

| Condition | Correct | Wrong | Gave up |
|---|---|---|---|
| Metadata + OCR, learned scorer (P0, the product) | 58.5% | 0.0% | 41.5% |
| Metadata + OCR, rules (B4) | 84.7% | 0.0% | 15.3% |
| OCR only, learned | 8.0% | 2.9% | 89.1% |
| OCR only, rules (B2) | 8.0% | 2.9% | 89.1% |
| Metadata only, rules (B1) | 84.7% | 0.0% | 15.3% |

**Failure found.** Real apps expose one visible control as several nested UIA elements with the same name: in Paint, "File" is a menu item and a button with the same box plus a text label; in Calculator, "Log" is a button plus its label. The learned scorer reads these as duplicate labels and gives up. The synthetic training pages never contain this nesting.

## v2: after the fix (`grounding_real_v2.json`, n = 240)

Fix: `collapse_nested` folds same-name elements whose boxes nest into one candidate (one visible control = one candidate), now used by `screen.click`. The fix was designed after looking at v1 failures, so v2 on Calculator and Paint is **not** a clean held-out result; Character Map was added unseen as a fresh check, but it has only 8 controls.

| Condition | Correct | Wrong | Gave up |
|---|---|---|---|
| Metadata + OCR, learned, as trained | 68.3% | 0.0% | 31.7% |
| **Metadata + OCR, learned, with fix** | **79.2%** | **0.0%** | 20.8% |
| Metadata + OCR, rules, with fix | 87.5% | 0.0% | 12.5% |
| OCR only, learned / rules | 10.0% / 10.4% | 4.2% / 4.2% | 85.8% / 85.4% |

Per app (learned with fix / rules with fix): Calculator 89.1% / 93.5%, Paint 71.4% / 82.9%, Character Map 8/8 / 8/8. The v1 and v2 rows differ in n because Paint showed fewer controls in the second run (UI state differs between launches).

## What this means for the product
- **No wrong clicks** with metadata in either run, for both scorers.
- **On real apps with metadata, the rules beat the learned scorer** (87.5% vs 79.2%). This reverses the synthetic result (90.3% vs 63.1%), so the synthetic-to-real gap is real. The remaining learned abstentions are near-identical long names ("Vertical Small Decrease" vs "Vertical Large Decrease", "Open history flyout" vs "Open memory flyout"), which the synthetic generator does not produce.
- **Reading alone is not enough in real apps:** most controls are icons or symbols, so their names are not visible text (Calculator's "Seven" shows "7"). The OCR-only wrong clicks are Paint captions printed **below** icon buttons ("Image", "Shapes", "Select"); the click lands on the caption, not the button.
- `screen.click` is still allowlisted only for ORION's canvas demo, so nothing changes for users today. **Before any real app is allowlisted**, the scorer choice for apps with metadata should be made on a separate real-app validation set, not on this one.

## Threats to validity
- Three apps, one machine, one OCR engine; window states vary between launches.
- The instruction is the exact UIA name, which favours exact-match rules; users' wording would differ.
- "Correct" means the click point is inside the control; it does not check what the app did.
