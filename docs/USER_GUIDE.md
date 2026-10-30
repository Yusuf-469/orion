# ORION user guide

ORION is an assistant that operates your Windows computer for you. Tell it, or say it, what you want done: it plans the steps, uses the web, documents and apps, checks the result, and asks you before anything that matters. You can stop it at any moment.

## Install (portable, no Python needed)
1. Unzip `ORION-0.1.0-win64.zip` to a folder you own, for example `Documents\ORION` (not `Program Files`: ORION keeps its data next to the program).
2. **Install the local AI once:** get [Ollama](https://ollama.com) (free), then in a terminal run `ollama pull qwen2.5:7b` (about 4.7 GB). It runs on your computer; nothing is sent to the internet. Without it, ORION still understands its built-in phrases (see below).
3. **Once, for the web features:** in the ORION folder run `.\ORION.exe --install-browser` (Chromium, about 170 MB).
4. Double-click `ORION.exe`. Windows SmartScreen may warn about an unknown publisher (the build is not code-signed); choose **More info -> Run anyway** only if you got the zip from the project author.
5. **Check the install:** `.\ORION.exe --selftest` runs six checks and writes `selftest.json`; every check should say `"ok": true`.

## Using ORION
- **Type** what you want in the box on the Home screen and press Enter, or **talk**: click the microphone (or press **F9**), speak, and click it again (or F9) when you are done. No holding needed.
- ORION shows its **plan** on the left and each **step** it takes on the right, ticking off the plan as it goes, and says the result out loud.
- When it needs something from you, a dialog appears and ORION reads it aloud. You can click, or click the mic and **answer by voice**: "yes" / "no" for approvals, an option name or "the first one" for choices, or just your answer for questions.
- Try the chips under the box: **Compare products**, **Fill a form**, **Calculate**, **Table to report** (they use ORION's own test shop and forms, so nothing real is touched).

### Things you can ask
| Ask | What ORION does |
|---|---|
| "Compare the X and the Y and write me a document" | finds and reads their pages, writes a Word document with a spec table, pros and cons, who each suits, and sources |
| "Fill in the form at ... with my details and submit it" | answers every question from **Memory**, checks each answer against your details, shows you everything, submits only after your yes |
| "Find jobs on ... that match my CV (cv.pdf)" | reads your CV and every opening, writes a ranked shortlist with why each fits and skills to add; never applies |
| "Work out 15% of 2400 in Calculator" | uses Calculator and checks its answer against its own maths |
| "save the table from sales.html as report.csv then summarize it ..." | built-in phrases: files, CSV, Notepad, local forms (instant, no AI needed) |

### Memory and voice
- **Memory:** tell ORION your name and the details it should use for forms (email, phone, city, skills, preferences, a short CV). It stays on this computer.
- **Voice:** pick how ORION sounds. Press ▶ on any voice to hear it, click a card to choose it, set the speed, or switch speaking off. Natural voices appear if the optional voice pack is installed; otherwise the Windows voices are used.

## Staying in control
- **Kill switch:** the red **STOP** button, or **Ctrl+Alt+End** anywhere. Everything stops at once, including an open dialog.
- **Approvals:** anything that sends something (submitting a form, applying, posting) or deletes something always waits for your yes, and the dialog shows exactly what will be sent. Settings has an option to approve every change.
- **What ORION never does:** type passwords (sign in yourself in ORION's own browser window), get around CAPTCHAs, follow instructions written inside web pages or documents, change files outside its `workspace` folder without asking (it reads any file you point it to with a full path; it asks before creating, copying or deleting elsewhere, and twice in Windows system folders), or send anything you did not approve. If your goal says "don't apply" or "don't submit", the sending tool is not even available for that task.
- **Honest results:** the result line starting with "Verified by ORION" lists only what its tools actually confirmed (files created, forms sent).

## Where things are
- `workspace\`: ORION's own folder; documents it writes appear here (Settings -> Open the workspace folder).
- `data\`: your Memory (`profile.json`), settings, task history and logs (secrets redacted), and ORION's own browser profile.
- `orion.toml` (optional): settings such as permissions; unknown keys are rejected so a typo cannot switch off a safety setting.

## Troubleshooting
| Problem | Fix |
|---|---|
| "The local AI model is not available" | Start Ollama and run `ollama pull qwen2.5:7b` |
| Web goals fail with "Executable doesn't exist" | Run `.\ORION.exe --install-browser` once |
| "Microphone not available" | Check Windows Settings -> Privacy -> Microphone, and that a mic is plugged in |
| "Hotkey unavailable" | Another program uses Ctrl+Alt+End; use the STOP button |
| A task stops with "kept repeating" | Rephrase the goal more concretely, or break it into two goals |

## The original window
`ORION.exe --classic` opens the original tool console (pick a tool and arguments, dry-run by default).

## Known limits
The AI is a small local model: it is reliable on the task types above (measured 5/5 each on ORION's test site) but can make mistakes on unfamiliar sites, which is why sending always needs your approval. Desktop control covers Calculator, Paint, Notepad and ORION's own apps; other apps need to be added to the allowlist. Tested on Windows 11 at 100% and 125% scaling. Not code-signed.
