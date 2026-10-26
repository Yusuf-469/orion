# Stage 3 manual checklist (about 10 minutes)

Run `C:\ORION\.venv\Scripts\python.exe -m orion` from `C:\ORION`. Hover over the Goal box to see the supported phrases.

| # | Do | Expected |
|---|---|---|
| G1 | Dry run ticked. Goal: `create a file notes.txt containing hello then copy notes.txt to backup/notes.txt` | outcome **dry_run**; log shows both steps "would allow"; no files created |
| G2 | Untick dry run, same goal | outcome **verified_complete**; `workspace\backup\notes.txt` contains hello |
| G3 | Goal: `copy notes.txt` | blue box asks "Where should the copy … go?"; no task created |
| G4 | Goal: `send an email to my boss` | red box: planner does not understand, lists supported phrases; no task |
| G5 | Goal: `create a file ..\x.txt containing y` | red box: "Plan rejected … outside_workspace"; no task |
| G6 | Goal: `move notes.txt to archive/notes.txt` (default permissions) | copy done, delete **blocked** → outcome **partially_complete**; source kept |
| G7 | Goal: `list files` | outcome **unverified** (no completion checks; never reported as success) |
| G8 | Start G2-style goal with a new name, then close ORION from Task Manager mid-run (or just observe G9 if too fast) | on restart a yellow banner lists the interrupted task |
| G9 | Click "Resume (re-observe first)" | completed steps not repeated; outcome shown in the table |
| G10 | Select a row → "Delete selected history" → Yes; then "Clear all history" → No | row deleted; the rest kept; workspace files untouched |
