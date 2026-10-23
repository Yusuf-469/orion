"""Entry point: `python -m orion` or `orion`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from orion.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orion")
    parser.add_argument("--config", type=Path, help="path to orion.toml")
    args = parser.parse_args(argv)

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
