# Release checklist: ORION 0.1.0 (Gate C), 2026-10-28

| Item | Status | Evidence |
|---|---|---|
| Portable build (PyInstaller, one folder, windowed) | done | `packaging/build.ps1` -> `dist/ORION-0.1.0-win64.zip`, 220 MB zipped / 539 MB unzipped |
| Built app self-test, from a copy with Python removed from PATH | **passed 6/6** | `dist/selftest.json` written by the build script (files+verify, safety layer, browser, OCR, UI Automation, learned scorer) |
| Built app GUI end to end | **passed** | packaged `ORION.exe` driven through its real window: goal "click Export in the canvas demo", dry run off -> its own canvas helper launched, button found by OCR + learned scorer, clicked, `VERIFIED_COMPLETE`; exited with code 0 |
| `--install-browser` in the built app | **passed** | on the clean profile: real Chromium download, exit 0 in 26 s, into that user's `%LOCALAPPDATA%\ms-playwright` |
| Install on a clean Windows user profile | **passed** | new standard user `orion_test` (no Python, no Chromium): unzip -> self-test 5/6 (browser missing, with the fix hint) -> `--install-browser` -> self-test **6/6**; packaged GUI run as that user: canvas click `VERIFIED_COMPLETE`. `artifacts/acceptance_clean_profile.json` (transcribed from session output; raw files were deleted by mistake). Not tested: a second physical machine |
| Install and user guide | done | `docs/USER_GUIDE.md` |
| Developer install documented | done | `README.md` |
| Test suites | passed | offscreen 253 passed; real 20 passed + 1 skipped (hotkey held by another running ORION) |
| Benchmark | done | `benchmark/REPORT_v1.md` (435 runs, ORION 200/200, 0 safety violations) |
| Licences of bundled components | checked (package metadata) | PySide6 (LGPL-3.0, shipped as separate DLLs, so replaceable), Playwright (Apache-2.0), RapidOCR (Apache-2.0), onnxruntime (MIT), OpenCV (Apache-2.0), scikit-learn, SciPy, NumPy, Shapely (BSD), Pillow (MIT-CMU), pydantic, pyclipper (MIT), uiautomation (Apache-2.0), PyInstaller (GPLv2 with an exception that permits bundling). LGPL notice and licence texts should be added to the zip before public release |
| Code signing | not done | unsigned build; SmartScreen warning documented in the user guide |
| No credentials, private screenshots, user data or model weights in git | checked | `.gitignore` covers data/, workspace/, artifacts/, build/, dist/, images; the model ships inside the build only |
| Two full demo rehearsals + fallback recording | **human task** | to do by the author |
| Final report and slides | draft pending | evidence is in `STATUS.md`, `benchmark/REPORT_v1.md`, `research/reports/` |

## Claims audit (README, user guide, STATUS)
Corrected in this pass:
- README said "Current stage: 3 ... no UI clicking or browser control yet": outdated; rewritten.
- README said the learned scorer is "right far more often on unfamiliar layouts": true only on synthetic layouts; now states the real-app and benchmark results too.
- `config/orion.example.toml` granted only 3 permissions, which would have silently disabled Notepad, Calculator, clicking and the browser for anyone who copied it; fixed, with a regression test.

Checked and supported by evidence: kill switch and STOP (Stage 1 tests, benchmark I4), dry run by default (config test), delete always asks and goes to `.orion_trash`, workspace confinement (benchmark S1/S5), local pages only (browser tests), never submits (benchmark S7, M6), Notepad privacy guard (Notepad tests), crash-safe resume (benchmark I1-I3), "which one?" (benchmark F5), redaction of secrets in logs (observability tests).

Still to state plainly in the final report: clicking by sight is allowlisted to ORION's demo app only; the template planner covers fixed phrasings; the learned scorer showed no end-to-end gain over rules; human-eye checks M7 (physical hotkey press mid-task) and M9 (DPI crispness) are open.
