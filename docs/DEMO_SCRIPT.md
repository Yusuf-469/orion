# ORION demo script (5-7 minutes) and talking points

## Before the demo (10 minutes earlier)
- Plug in the laptop; close other apps; `ollama serve` running (`ollama ps` shows nothing loaded is fine).
- Start ORION (`ORION.exe` or `python -m orion`) once and run one task, so the AI model is loaded and warm (the first task after a cold start takes ~10 s longer).
- Memory: your name, plus test details for the form (email, "uses the app weekly", satisfaction 4, features, branch).
- Voice: pick a natural voice (e.g. Heart or George); speed ~1.05.
- Have a backup screen recording of the same flow, in case Wi-Fi or the projector misbehaves (everything shown runs offline except the real-web comparison).

## The flow
1. **Open (30 s).** "This is ORION, an AI agent that operates a Windows computer for you. Everything you'll see runs locally on this laptop, for free." Point at the core: it reacts to listening, thinking, acting, success.
2. **Voice + research (90 s).** Click the mic and say: *"Compare the Sony WH-1000XM5 and the Bose QuietComfort Ultra and write me a Word document."* While it works: the plan appears, the live view shows ORION's own browser, steps tick off. Open the document: spec table from the makers' pages and a review, pros and cons, verdict, sources. Point out: "the price claims are checked against the table by code; the model once contradicted itself, so I added that check."
3. **Long form, safely (90 s).** Click "Fill a form". It answers every question from Memory, runs its **self-check**, and the approval dialog lists every answer. Say **"yes"** out loud: hands-free. "It never submits without me, and if my goal says don't submit, the submit tool isn't even available to the model."
4. **Jobs from a CV (60 s).** "Find the jobs at [test careers page] that match my CV and write a shortlist." Ranked document, why each fits, skills to add, links. "It never applies on its own."
5. **Desktop (30 s).** "Work out 15% of 2400 in Calculator." It uses Calculator and checks the answer against its own maths.
6. **Control (30 s).** Start a task and press **Ctrl+Alt+End**: everything stops, the open dialog closes. "Safety lives in code outside the model: allowlisted tools, a policy engine, confirmations, a kill switch, verification of every result."
7. **Close (30 s).** Voice page: 44 local voices, including Hindi. "Built for people who find the mouse and keyboard hard: you can talk to it and answer it by voice."

## The engineering story (what impresses)
- **Same 7B model, 0-1/5 -> 5/5 on four real tasks by engineering around it** (`research/agent_eval/README.md`): page memory and a live view; forms answered by question with code ticking the boxes; an independent self-check before sending; least privilege per task enforced in code (after the model, told "do not apply", filled and submitted two applications, stopped only by my confirmation dialog); skills = pipelines in code with small model calls; repeat interception with concrete next steps.
- **Safety outside the model:** typed tool allowlist, policy engine (allow/confirm/deny from the tool's declared side effect), workspace confinement, prompt-injection handling (page text marked untrusted, invisible text stripped, injections planted in every test page, never followed), honest summaries (only what tools verified).
- **Benchmark:** 40 tasks x 5 runs, 200/200, 0 safety violations; without the recovery engine 40% on failure tasks (`benchmark/REPORT_v1.md`).
- **ML research (clicking by what is visible):** learned re-ranker over UIA + OCR candidates, 63% -> 90% on held-out synthetic layout families with fewer wrong clicks; SigLIP LoRA fine-tune passed the pre-registered rule but was not deployed (cost, no end-to-end gain); conformal abstention coverage measured in- and out-of-distribution; an honest synthetic-to-real gap with identified causes (`research/reports/`).

## Likely questions
- **What if the model is wrong?** Every action is validated; sending needs approval; the self-check compares answers with your details; results are verified by the tools, and the summary only claims what was verified.
- **Why a local 7B model?** Privacy and zero cost; the engineering makes it reliable on the supported task types. A stronger model can be plugged in (Settings -> model).
- **What did you build vs reuse?** Built: the agent loop, tools, policy, verification, recovery, skills, self-check, interface, voice integration, research pipeline and benchmark. Reused (credited): Qwen2.5-7B, faster-whisper, Kokoro voices, Playwright, UI Automation, RapidOCR, SigLIP, PySide6/pywebview.
- **Limits?** Measured on fictional test sites plus a few real pages; unfamiliar sites can still trip it, which is why approval stays mandatory. Desktop control covers a small allowlist of apps.
