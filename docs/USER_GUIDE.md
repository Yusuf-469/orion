# ORION user guide

ORION is a desktop assistant for Windows that carries out tasks for you: working with files in its own folder, reading local web pages, filling forms, using Notepad and Calculator, and clicking buttons by what it sees on screen. It checks its own work, asks before anything risky, and can be stopped at any moment.

## Install (portable, no Python needed)
1. Unzip `ORION-0.1.0-win64.zip` to a folder you own, for example `Documents\ORION` (not `Program Files`: ORION keeps its data next to the program).
2. Double-click `ORION.exe`. Windows SmartScreen may warn about an unknown publisher because the build is not code-signed; choose **More info -> Run anyway** only if you got the zip from the project author.
3. **Once, for the browser features:** open a terminal in the folder and run `.\ORION.exe --install-browser` (downloads Chromium, about 170 MB, into `%LOCALAPPDATA%\ms-playwright`). Everything else works without it.
4. **Check the install:** `.\ORION.exe --selftest` runs six quick checks in a temporary folder (planning and verification, the safety layer, the browser, OCR, UI Automation, the click model) and writes `selftest.json`. Every check should say `"ok": true`.

## Using it
1. Type a goal in **Goal** (or pick one from **Examples...**) and press **Plan & run**.
2. **Dry run** is ticked by default: ORION shows what it *would* do and changes nothing. Untick it to really run the task.
3. The log shows each step and how ORION checked it. The final line says whether the task was **verified complete**, **partially complete**, **blocked**, **failed**, **unverified** (done, but ORION had no way to check) or **cancelled**.

### What you can ask (built-in planner)
| Goal | Example |
|---|---|
| Create, copy, back up, move, read, list, delete files | `create a file notes.txt containing "buy milk"` |
| Save a table from a local page as CSV, summarize it | `save the table from sales.html as report.csv then summarize report.csv into summary.txt` |
| Notepad: open, type into, close | `type "Meeting moved to 4 pm" into summary.txt in notepad` |
| Fill a local form (never submits) | `fill the form on signup.html with name "Asha Rao" email "asha@example.com"` |
| Calculator | `calculate 1250*12+300 in calculator` |
| Click a button by what is visible (demo app) | `click Export in the canvas demo` |

Chain steps with **then**. If a detail is missing (a file name, a destination, the text to write), ORION asks instead of guessing. Requests it does not understand are refused, not guessed. An optional local AI planner (Ollama) handles freer wording; every plan it makes is shown to you for approval first.

## Staying in control
- **Kill switch:** press **Ctrl+Alt+End** anywhere, or the red **STOP** button. Everything stops at once; nothing after that point runs. If another program already uses Ctrl+Alt+End, ORION tells you at startup and STOP still works.
- **Confirmations:** deleting always asks first (and only works if you allowed it in `orion.toml`); deleted files go to `workspace\.orion_trash`. Each "yes" covers that one action only.
- **"Which one did you mean?"** If two buttons match, ORION shows both and clicks only the one you pick. "Neither" clicks nothing.
- **What ORION never does:** submit forms, send, post, buy or pay; touch files outside its `workspace` folder; open web pages other than the local ones in `workspace\pages`; read your other Notepad tabs; follow instructions written inside web pages or documents.
- **If it crashes:** on restart ORION offers to resume. It re-checks what already happened and never blindly repeats a step whose result is unknown.

## Where things are
- `workspace\`: the only folder ORION's file tools can use. Demo pages are in `workspace\pages`.
- `data\`: task history (`orion.db`) and logs (`data\logs`, secrets redacted). Delete a task from the history list, or clear it all.
- `orion.toml` (optional, next to `ORION.exe`): settings. Start from `config\orion.example.toml` in the source; unknown keys are rejected so a typo cannot switch off a safety setting.
- Screenshots used for clicking are kept in memory only, never saved.

## Troubleshooting
| Problem | Fix |
|---|---|
| Browser goals fail with "Executable doesn't exist" | Run `.\ORION.exe --install-browser` once |
| "another window covers ..." / "did not click" | Something was on top of the target window; bring it to the front and run the goal again |
| A dialog appeared over Notepad | ORION asks whether to close it (like Cancel); say no to stop the task safely |
| Task says "unverified" | It ran, but ORION had nothing it could check it against (e.g. reading or listing files) |
| Self-test fails | Open `selftest.json`; each failed check says why |

## Uninstall
Delete the ORION folder. Optionally delete `%LOCALAPPDATA%\ms-playwright` (the browser), if no other program uses it.

## Known limits
Built-in planner understands the phrases above only; clicking by sight is enabled only for ORION's demo app (other apps need a safety review); tested on Windows 11 with 100% and 125% display scaling; not code-signed.
