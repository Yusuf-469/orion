# Third-party work used in ORION

## Ideas and methods adapted (no code copied)
- **ai-job-search** by Mads Lorentzen, MIT licence (github.com/ai-job-search-dev/ai-job-search). ORION's `jobs.shortlist` adapts its job-evaluation method: an eligibility gate and a language gate judged on the advert's own words before any scoring, location as a separate check, and separate scored dimensions (technical skills, experience matched on the function of the work, career alignment). ORION adds its own guard that a gate may only fail on a sentence that actually appears in the advert.

  MIT licence notice of the original: Copyright (c) 2026 Mads Lorentzen. Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, subject to the condition that the above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

- **ui-ux-pro-max** by Next Level Builder, MIT licence (github.com/nextlevelbuilder/ui-ux-pro-max-skill). Its interface-quality rules shaped ORION's UI pass: visible focus rings, 44px touch targets, SVG icons instead of symbol characters, 16px base text, reduced-motion support and the Space Grotesk / DM Sans pairing. The icons themselves were drawn for ORION.

## Fonts (bundled)
Space Grotesk (Florian Karsten) and DM Sans (Colophon Foundry), both SIL Open Font License 1.1, shipped unmodified as woff2 in `src/orion/ui/web/fonts/`.

## Models and libraries (used, not modified)
Qwen2.5-7B-Instruct (Apache-2.0), faster-whisper (MIT), Kokoro-82M via kokoro-onnx (Apache-2.0 model, MIT runtime; optional, not bundled because espeak-ng is GPL), SigLIP base (Apache-2.0), RapidOCR (Apache-2.0), Playwright (Apache-2.0), uiautomation (Apache-2.0), PySide6 (LGPL-3.0), pywebview (BSD-3), python-docx (MIT), pypdf (BSD-3), scikit-learn (BSD-3), onnxruntime (MIT), sounddevice (MIT), PyInstaller (GPL-2.0 with bundling exception).

## Reviewed and not used
- **Auto_job_applier_linkedIn** (GodsScion, MIT): mass auto-applies on LinkedIn with the user's stored password and without per-application approval; LinkedIn's terms forbid such automation. Contrary to ORION's rules (no passwords, approval before sending).
