# ORION

A general-purpose autonomous Windows computer-use agent (final-year project). See `CLAUDE.md`, `docs/12_WEEK_PLAN.md` and `STATUS.md`.

**Current stage: 3 (goals, planning, persistence, resume).** ORION plans simple file/app goals with a deterministic template planner, validates the plan, runs it through permissioned tools confined to `workspace/`, verifies the result, and resumes safely after a crash. No UI clicking/typing or browser control yet (Stage 4).

## Developer setup (Windows, Python 3.11)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m orion            # run the app
```

## Tests
```powershell
$env:QT_QPA_PLATFORM='offscreen'; .\.venv\Scripts\python.exe -m pytest -m "not real" -s
Remove-Item Env:QT_QPA_PLATFORM;  .\.venv\Scripts\python.exe -m pytest -m real
```
Markers: `mock` (simulated actions), `real` (opens an ORION window on the desktop), `safety`, `ui`.

## Visual grounding model (optional, ~20 min, CPU)
ORION clicks by what is visible. Without a trained model it uses rules; with one it is right far more often
on unfamiliar layouts with fewer wrong clicks. Build it locally (weights are not committed):
```powershell
.\.venv\Scripts\python.exe research\data_collection\render_synth.py --out research\data_collection\out\v1 --n 600
.\.venv\Scripts\python.exe research\training\train_grounding.py --data research\data_collection\out\v1 --model-out artifacts\models\grounding_p0_candidate.joblib
# promote only if the printed P0 result beats B4 on wrong clicks and correct answers:
Copy-Item artifacts\models\grounding_p0_candidate.joblib artifacts\models\grounding_p0.joblib
```

## Config
Copy `config/orion.example.toml` to `orion.toml`. Unknown keys are rejected.
