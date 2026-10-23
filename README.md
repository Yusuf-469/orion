# ORION

A general-purpose autonomous Windows computer-use agent (final-year project). See `CLAUDE.md`, `docs/12_WEEK_PLAN.md` and `STATUS.md`.

**Current stage: 1 (desktop shell).** Tasks are simulated; ORION does not control the desktop yet.

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

## Config
Copy `config/orion.example.toml` to `orion.toml`. Unknown keys are rejected.
