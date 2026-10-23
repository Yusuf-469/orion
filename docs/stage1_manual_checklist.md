# Stage 1 manual UI checklist

Run: `C:\ORION\.venv\Scripts\python.exe -m orion` from `C:\ORION`. Tick each item and note the date.

| # | Check | Expected | Result |
|---|---|---|---|
| M1 | App opens | Window "ORION (Stage 1 shell)"; status bar says the hotkey was registered | |
| M2 | Dry-run default | "Dry run" is ticked; Run → task ends **skipped**; log says "10 actions planned, 0 executed" | |
| M3 | Live simulated task | Untick dry-run, Run → steps appear one per second; window can be moved/resized smoothly | |
| M4 | STOP button | During M3, click STOP ALL → task **cancelled** within 2 s; red "Kill switch ENGAGED" label | |
| M5 | Blocked while engaged | Click Run while engaged → red error "kill switch engaged…"; no new task | |
| M6 | Reset | Click "Reset kill switch" → label turns green; Run works again | |
| M7 | Physical hotkey | Start a live task, click into **another app** (e.g. VS Code), press **Ctrl+Alt+End** → ORION task cancelled | |
| M8 | Injected failure | Tick "Inject failure at step 5", run live → task **failed**, red error banner shows "injected test failure" | |
| M9 | Both monitors | Repeat M3 on the 100% and the 125% monitor; text is crisp, nothing clipped | |
| M10 | Log file | `data/logs/orion.jsonl` has one JSON object per line, including the kill-switch event | |
| M11 | Close while running | Start a live task, close the window → app exits within ~3 s, no error dialog | |
