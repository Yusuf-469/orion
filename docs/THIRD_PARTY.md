# Third-party work used in ORION

## Ideas and methods adapted (no code copied)
- **ai-job-search** by Mads Lorentzen, MIT licence (github.com/ai-job-search-dev/ai-job-search). ORION's `jobs.shortlist` adapts its job-evaluation method: an eligibility gate and a language gate judged on the advert's own words before any scoring, location as a separate check, and separate scored dimensions (technical skills, experience matched on the function of the work, career alignment). ORION adds its own guard that a gate may only fail on a sentence that actually appears in the advert.

  MIT licence notice of the original: Copyright (c) 2026 Mads Lorentzen. Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, subject to the condition that the above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

- **ui-ux-pro-max** by Next Level Builder, MIT licence (github.com/nextlevelbuilder/ui-ux-pro-max-skill). Its interface-quality rules shaped ORION's UI pass: visible focus rings, 44px touch targets, SVG icons instead of symbol characters, 16px base text, reduced-motion support and the Space Grotesk / DM Sans pairing. The icons themselves were drawn for ORION.

- **browser-use** (github.com/browser-use/browser-use), MIT. ORION's page snapshot (`src/orion/tools/web/session.py`) adopts its clickability heuristics: elements with click handlers or `tabindex`, extra ARIA widget roles, the outermost `cursor: pointer` element of a widget, open shadow roots, and telling the agent how much of the page lies above and below. Re-implemented in ORION's own snapshot script; no browser-use code or dependency.

- **Agent-S** by Simular (github.com/simular-ai/Agent-S), Apache-2.0. Two ideas re-implemented in ORION's agent loop: experience memory (`src/orion/agent/experience.py`: verified successful step sequences, stored locally in SQLite with secrets redacted, offered as advice on similar goals) and reflection (a click or keypress that leaves the screen unchanged is flagged to the model as probably ineffective). No Agent-S code is used; its UI-TARS grounding model is not used (too large for the 8 GB GPU next to the local LLM).

- **UFO** by Microsoft (github.com/microsoft/UFO), MIT. Its practice of driving Office through the applications' own APIs instead of clicking led to `src/orion/tools/office.py` (excel.read, excel.write, office.export_pdf over COM), written for ORION: a private hidden Office instance per call, macros forced off, read-only opening, new files only, read-back verification. No UFO code is used.
- **Open Interpreter** (github.com/openinterpreter/openinterpreter), Apache-2.0: reviewed, not used. It is now a coding-agent harness that works by running model-written shell code, which ORION's rules forbid.

## Code adapted
- **OmniParser** by Microsoft (github.com/microsoft/OmniParser), code MIT. `src/orion/grounding/detector.py` adapts the YOLOv9 detector wrapper (`util/yolov9.py`): letterbox preprocessing, anchor-free decode and NMS. Weight `icon_detect_v3` (microsoft/OmniParser-v2.0 on Hugging Face, revision refs/pr/37), MIT, downloaded to `models/omniparser/` and not committed. Only the MIT detector is used; the older Ultralytics-based AGPL detectors and the caption models are not.

## Fonts (bundled)
Space Grotesk (Florian Karsten) and DM Sans (Colophon Foundry), both SIL Open Font License 1.1, shipped unmodified as woff2 in `src/orion/ui/web/fonts/`.

## Models and libraries (used, not modified)
Qwen2.5-7B-Instruct (Apache-2.0), faster-whisper (MIT), Kokoro-82M via kokoro-onnx (Apache-2.0 model, MIT runtime; optional, not bundled because espeak-ng is GPL), SigLIP base (Apache-2.0), RapidOCR (Apache-2.0), Playwright (Apache-2.0), uiautomation (Apache-2.0), PySide6 (LGPL-3.0), pywebview (BSD-3), python-docx (MIT), pypdf (BSD-3), scikit-learn (BSD-3), onnxruntime (MIT), sounddevice (MIT), PyInstaller (GPL-2.0 with bundling exception).

## Reviewed and not used
- **Auto_job_applier_linkedIn** (GodsScion, MIT): mass auto-applies on LinkedIn with the user's stored password and without per-application approval; LinkedIn's terms forbid such automation. Contrary to ORION's rules (no passwords, approval before sending).
