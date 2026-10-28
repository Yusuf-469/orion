# ORION

A general-purpose autonomous Windows computer-use agent (final-year project). See `CLAUDE.md`, `docs/12_WEEK_PLAN.md` and `STATUS.md` (every capability with its evidence).

**Current stage: 9b (packaging and release).** ORION turns a goal into a validated plan, runs it through permissioned tools (files in its workspace, Notepad, Calculator, a local browser, clicking by what is visible), verifies the result, recovers from common problems (a dialog in the way, a lost tab, two matching buttons), and resumes safely after a crash. A kill switch (Ctrl+Alt+End or STOP) and dry-run mode are always available. Results: `benchmark/REPORT_v1.md` (40 tasks x 5 runs) and `research/reports/`.

**Using ORION:** see [docs/USER_GUIDE.md](docs/USER_GUIDE.md). The portable build is a zip; no Python needed.

## Developer setup (Windows, Python 3.11)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m playwright install chromium   # once, for the browser tools
.\.venv\Scripts\python.exe -m orion                          # run the app
.\.venv\Scripts\python.exe -m orion --selftest               # headless smoke test -> selftest.json
```

## Tests
```powershell
$env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest -m "not real" -s
Remove-Item Env:QT_QPA_PLATFORM;  .\.venv\Scripts\python.exe -m pytest -m real    # leave the PC alone
```
Markers: `mock` (simulated actions), `real` (opens ORION's own windows on the desktop), `safety`, `ui`.

## Benchmark
```powershell
.\.venv\Scripts\python.exe -m benchmark.run_benchmark --runs 5    # ~20 min, leave the PC alone
```
Protocol: `benchmark/PROTOCOL.md`. Results land in `benchmark/results/<run id>/`.

## Packaging (portable release)
```powershell
.\.venv\Scripts\python.exe -m pip install "pyinstaller>=6.10"
powershell -ExecutionPolicy Bypass -File packaging\build.ps1    # build -> self-test the built app -> zip
```
Output: `dist\ORION-<version>-win64.zip` (about 220 MB). The build includes the grounding model if `artifacts/models/grounding_p0.joblib` exists; otherwise ORION uses rule-based grounding.

## Visual grounding model (optional, ~20 min, CPU)
ORION clicks by what is visible. Without a trained model it uses rules. The learned scorer is right more often on unseen synthetic layouts (90% vs 63%, `research/reports/grounding_v1.md`), but on real apps with accessibility data the rules did better (`research/reports/grounding_real_v1.md`) and in the end-to-end benchmark both were equal. Build it locally (weights are not committed):
```powershell
.\.venv\Scripts\python.exe research\data_collection\render_synth.py --out research\data_collection\out\v1 --n 600
.\.venv\Scripts\python.exe research\training\train_grounding.py --data research\data_collection\out\v1 --model-out artifacts\models\grounding_p0_candidate.joblib
# promote only if the printed P0 result beats B4 on wrong clicks and correct answers:
Copy-Item artifacts\models\grounding_p0_candidate.joblib artifacts\models\grounding_p0.joblib
```

## Config
Copy `config/orion.example.toml` to `orion.toml` (next to ORION.exe for the portable build). Unknown keys are rejected.
