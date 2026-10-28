"""Entry point: `python -m orion` or `orion` (or ORION.exe when packaged).

Extra modes (used by the packaged build, also work from source):
  --selftest [FILE]   run a headless smoke test in a temp folder, write JSON results (default selftest.json)
  --install-browser   download Playwright's Chromium once (needed by the browser tools; ~170 MB)
  --run-helper NAME   run one of ORION's own bundled helper apps (allowlisted; used for the canvas demo)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from orion.config import load_config

HELPERS = ("demo/apps/canvas_buttons.py",)   # the only scripts --run-helper may run


def run_helper(name: str, args: list[str]) -> int:
    import runpy

    from orion import resources
    if name not in HELPERS:
        print(f"unknown helper {name!r}", file=sys.stderr)
        return 2
    sys.argv = [name, *args]
    runpy.run_path(str(resources.path(name)), run_name="__main__")
    return 0


def install_browser() -> int:
    import subprocess

    from playwright._impl._driver import compute_driver_executable, get_driver_env
    driver = compute_driver_executable()
    cmd = [*driver, "install", "chromium"] if isinstance(driver, tuple) else [str(driver), "install", "chromium"]
    return subprocess.run(cmd, env=get_driver_env()).returncode


def _attach_console() -> None:
    """The packaged ORION.exe is a window app with no console; command-line modes still print progress."""
    import ctypes
    if not ctypes.windll.kernel32.AttachConsole(-1):   # the console it was started from, else a new one
        ctypes.windll.kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orion")
    parser.add_argument("--config", type=Path, help="path to orion.toml")
    parser.add_argument("--selftest", nargs="?", const="selftest.json", metavar="FILE")
    parser.add_argument("--install-browser", action="store_true")
    parser.add_argument("--run-helper", metavar="NAME")
    args, rest = parser.parse_known_args(argv)

    from orion import resources
    if resources.FROZEN:
        # Packaged Playwright would look for Chromium inside the bundle; use the standard per-user folder.
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                              str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"))
        if args.config is None:
            # Portable build: data/, workspace/ and orion.toml live next to ORION.exe, however it was started.
            os.chdir(Path(sys.executable).parent)
    if args.run_helper:
        return run_helper(args.run_helper, rest)
    if rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
    if resources.FROZEN and (args.install_browser or args.selftest) and sys.stdout is None:
        _attach_console()
    if args.install_browser:
        return install_browser()
    if args.selftest:
        from orion.app.selftest import run_selftest
        return run_selftest(Path(args.selftest))

    cfg = load_config(args.config)
    from orion.observability import setup_logging
    log_path = setup_logging(cfg.log_dir, cfg.log_level)
    log = logging.getLogger("orion.app")
    log.info("starting ORION", extra={"event": {"kind": "startup", "data_dir": str(cfg.data_dir),
                                               "dry_run_default": cfg.dry_run_default}})

    from PySide6.QtWidgets import QApplication

    from orion.app.main_window import MainWindow
    from orion.memory import TaskStore

    app = QApplication(sys.argv[:1])
    store = TaskStore(cfg.db_path)
    win = MainWindow(cfg, store)
    win.statusBar().showMessage(f"{win.statusBar().currentMessage()}  |  log: {log_path}")
    win.show()
    code = app.exec()
    store.close()
    log.info("ORION exited", extra={"event": {"kind": "shutdown", "code": code}})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
