# ORION

**An AI agent that operates your Windows computer for you: tell it (or say it) what you want done, and it does it, checks it, and asks before anything that matters.** Built to make computers easy for anyone, including people who find the mouse and keyboard hard.

What it does today, on this laptop, fully local and free:
- **Researches and writes:** "Compare these two headphones and write me a Word document": finds the pages, reads them, writes a spec table, pros and cons and a verdict, with sources.
- **Fills long forms** (including Google-Forms-style questions) from what you told it, checks every answer against your details, shows you everything, and submits only when you say yes.
- **Finds jobs that match your CV** and writes a ranked shortlist with why each fits and which skills to add. It never applies on its own.
- **Uses desktop apps:** Calculator, Notepad, Paint and its own apps, through Windows accessibility and by what is visible on screen.
- **Talks and listens:** click the mic or press F9 and speak; answer its questions and approvals by voice. 44 local voices (natural neural voices incl. Hindi and British English, plus Windows voices).
- **Stays under your control:** STOP button and Ctrl+Alt+End kill switch, approval before sending/submitting/deleting, never types passwords, treats web pages as information, not instructions; every result is verified, and its summary says only what its tools confirmed.

How it works: a local language model (Qwen2.5-7B via Ollama) plans the next step; every action goes through typed, permissioned tools and a policy engine outside the model; a self-check compares form answers with your details before sending; "skills" run common multi-step jobs as reliable pipelines. Measured results: `research/agent_eval/README.md` (four real tasks, 5/5 each), `benchmark/REPORT_v1.md` (40 tasks x 5 runs, 200/200, 0 safety violations). The machine-learning research behind clicking by sight (learned grounding, SigLIP fine-tuning, conformal abstention, synthetic-to-real gap) is in `research/reports/`. Project rules: `docs/PROJECT_RULES.md`; plan: `docs/12_WEEK_PLAN.md`; every capability with its evidence: `STATUS.md`.

**Using ORION:** see [docs/USER_GUIDE.md](docs/USER_GUIDE.md). The portable build is a zip; no Python needed. Needs [Ollama](https://ollama.com) with `qwen2.5:7b` for the AI agent (the built-in phrase planner works without it).

## Developer setup (Windows, Python 3.11)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m playwright install chromium   # once, for the browser tools
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"      # optional: speech input (faster-whisper)
ollama pull qwen2.5:7b                                       # the local AI model for the agent (~4.7 GB)
.\.venv\Scripts\python.exe -m orion                          # run the app (the ORION interface)
.\.venv\Scripts\python.exe -m orion --classic                # the original tool-console window
.\.venv\Scripts\python.exe -m orion --selftest               # headless smoke test -> selftest.json
.\.venv\Scripts\python.exe scripts\agent_trial.py form       # agent trials: compare | form | calc | jobs
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
Output: `dist\ORION-<version>-win64.zip` (about 290 MB). The build includes the grounding model if `artifacts/models/grounding_p0.joblib` exists; otherwise ORION uses rule-based grounding.

Natural voices (optional, not bundled because their pronunciation helper espeak-ng is GPL): `pip install kokoro-onnx soundfile` and put `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin` (from the kokoro-onnx releases) in `artifacts/models/kokoro/`. Without them ORION speaks with the Windows voices.

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
