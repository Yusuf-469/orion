# ORION benchmark v1: results (run 20261028-220054)

**Setup.** 40 tasks in 8 categories, pre-registered in [PROTOCOL.md](PROTOCOL.md) and committed before the run (`4f70e2c`, protocol count fixed in `83cd726`; the run used `83cd726`). 5 runs per task per condition, 435 runs in total, about 20 minutes on the development laptop (Windows 11, two monitors at 100% and 125%). Raw runs: `results/20261028-220054/runs.jsonl`; generated tables: `results/20261028-220054/summary.md`. Every pass/fail comes from an independent check of the world (files, the demo app's click log, the form's state), not from ORION's own verifier.

## Headline

| Condition | Success (95% CI) | Safety violations | Failure-and-recovery tasks |
|---|---|---|---|
| **C3 ORION** | **200/200 = 100% (98-100)** | **0** | 25/25 |
| C2 ORION, rule grounding instead of the learned scorer (grounding tasks only) | 50/50 = 100% (93-100) | 0 | 10/10 |
| C1 fixed script, same tool calls, no planning/verification/recovery | 145/160 = 91% (85-94) | 0 | 10/25 |
| A_norec ORION without recovery (failure tasks only) | 10/25 = 40% (23-59) | 0 | 10/25 |

## What the comparisons show
- **Recovery is what makes ORION robust.** The dialog-over-Notepad (F1), tab-switched (F3) and two-matching-buttons (F5) tasks pass 5/5 with ORION and **0/5** without recovery and as a plain script. Without recovery, ORION still stops safely and reports the task as only partially complete (15/15 of its real failures were flagged; no false "complete" claims).
- **Safety does not depend on the planner.** All 35 safety runs pass in every condition with 0 violations, including the plain script: workspace limits, permissions and delete confirmation live in ORION's tool runtime, outside any planner or model. The scripted runs also show the tools protecting themselves (Notepad refuses to type while a dialog blocks it; files are never overwritten).
- **Learned vs rule grounding: no difference on this benchmark.** Both found the right button in 50/50 runs on the canvas demo (both monitors, light and dark, shuffled layout), with 0 wrong clicks. These canvas tasks are easy for both; the learned scorer's advantage was on varied synthetic layouts, and on real apps the rules were better (see `research/reports/grounding_real_v1.md`). This benchmark gives **no evidence** that the learned scorer helps end-to-end.
- **Honest outcomes.** ORION never claimed "complete" when the checker said otherwise (0 false success claims in all conditions). It reported "unverified" in 25 runs where it had no way to confirm the result (read, list, Calculator, form fill); all 25 had in fact succeeded. For Calculator and form fill the tools do check their own result, but the task outcome cannot use those checks yet; this is a known gap.
- **Asking.** All 20 ambiguous-request runs asked or refused to guess, and nothing changed on disk.

## Cost
Median latency 0.75 s per task (p95 7.8 s; desktop tasks take 2-10 s, file tasks under 1 s). Peak RAM of the agent process 530 MB; mean CPU about 2 cores (local OCR); no GPU used (torch is not loaded); grounding model 1 MB on disk.

## Changes after the run (disclosed)
- **Metric:** the first summary counted "unverified" as a false alarm (25 for C3). Failure detection now counts only failed/blocked/partial/cancelled as flagged and reports "unverified" separately. Same raw runs, re-summarized with `--resummarize`.
- **Product:** task S7 ("fill the form ... and submit it") passed (never submitted), but ORION dropped "submit" without telling the user. The validator now warns `will_not_do` for submit/send/post/buy/pay requests, and the window shows the note (unit tests added). Not re-benchmarked.

## Limitations
- The tasks are within what the template planner understands, and the fixtures were built by the same developer as ORION; 100% shows reliability on known task types, not general ability. Open-ended requests (the LLM planner) are not in this benchmark.
- Display scaling is covered by the two monitors (100% and 125%), not by changing Windows scaling; slow-app timeouts are not covered.
- The Calculator check reads the tool's own output, because ORION closes its window.
- 5 runs per task on one machine; confidence intervals are wide for small categories.
