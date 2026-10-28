"""Where ORION's bundled files live: the repository when run from source, the bundle when packaged."""

from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def root() -> Path:
    """Repository root (source) or the PyInstaller bundle folder (packaged)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def path(*parts: str) -> Path:
    return root().joinpath(*parts)


def helper_command(script: str, *args: str) -> list[str]:
    """Command that runs one of ORION's helper scripts (e.g. the canvas demo app) as its own process.

    From source: pythonw + the script. Packaged: ORION's own exe with --run-helper (no Python on the PC).
    """
    if FROZEN:
        return [sys.executable, "--run-helper", script, *args]
    exe = Path(sys.executable).with_name("pythonw.exe")
    return [str(exe if exe.exists() else sys.executable), str(path(script)), *args]
