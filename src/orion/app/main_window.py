"""Stage 1 desktop shell: task input, task list, live log, kill switch, dry-run."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from orion.app import hotkey
from orion.config import OrionConfig
from orion.execution import Action, DryRunExecutor, RealExecutor
from orion.memory import TaskStore
from orion.orchestration.cancel import KillSwitch, KillSwitchEngaged
from orion.orchestration.runner import TaskRunner, simulated_action

log = logging.getLogger("orion.app")

_STATUS_COLORS = {
    "running": "#1565c0", "succeeded": "#2e7d32", "failed": "#c62828",
    "cancelled": "#ef6c00", "skipped": "#6a1b9a",
}


class _EventBridge(QObject):
    """Carries runner events from worker threads to the UI thread (queued signal)."""
    event = Signal(dict)


def build_simulated_task(cfg: OrionConfig, inject_failure: bool) -> list[Action]:
    actions = [simulated_action(f"simulated step {i + 1}", cfg.simulated_step_seconds)
               for i in range(cfg.simulated_steps)]
    if inject_failure:
        def fail(token):
            raise RuntimeError("injected test failure")
        k = min(4, len(actions) - 1)
        actions[k] = Action(name=f"simulated step {k + 1} (injected failure)", fn=fail)
    return actions


class MainWindow(QMainWindow):
    def __init__(self, cfg: OrionConfig, store: TaskStore, register_hotkey: bool = True):
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.kill_switch = KillSwitch()
        self._bridge = _EventBridge()
        self._bridge.event.connect(self._on_event)
        self.runner = TaskRunner(store, self.kill_switch, on_event=self._bridge.event.emit)
        self._threads: list[threading.Thread] = []
        self._hotkey_registered = False
        self._closed = False

        self._ks_poll = QTimer(self)
        self._ks_poll.setInterval(200)
        self._ks_poll.timeout.connect(self._update_ks_label)

        self.setWindowTitle("ORION (Stage 1 shell)")
        self.resize(1000, 700)
        self._build_ui()
        self._refresh_tasks()
        if register_hotkey:
            self._register_hotkey()

    # --- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        banner = QLabel("Stage 1 shell: every task runs a SIMULATED job that only waits. "
                        "No real desktop, browser or file actions exist yet.")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#fff3cd;color:#664d03;padding:6px;border-radius:4px;")

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Describe a task (Stage 1: text is recorded, not interpreted)")
        self.task_input.returnPressed.connect(self.start_task)
        self.dry_run_box = QCheckBox("Dry run (plan only, execute nothing)")
        self.dry_run_box.setChecked(self.cfg.dry_run_default)
        self.fail_box = QCheckBox("Inject failure at step 5")
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.start_task)

        row = QHBoxLayout()
        row.addWidget(self.task_input, 1)
        row.addWidget(self.dry_run_box)
        row.addWidget(self.fail_box)
        row.addWidget(self.run_btn)

        self.stop_btn = QPushButton(f"STOP ALL  ({self.cfg.kill_hotkey.upper()})")
        self.stop_btn.setMinimumHeight(44)
        f = QFont(); f.setBold(True); f.setPointSize(11)
        self.stop_btn.setFont(f)
        self.stop_btn.setStyleSheet("QPushButton{background:#c62828;color:white;border-radius:4px;}"
                                    "QPushButton:pressed{background:#8e0000;}")
        self.stop_btn.clicked.connect(lambda: self.engage_kill_switch("STOP button"))

        self.ks_label = QLabel()
        self.reset_btn = QPushButton("Reset kill switch")
        self.reset_btn.clicked.connect(self.reset_kill_switch)
        ks_row = QHBoxLayout()
        ks_row.addWidget(self.ks_label, 1)
        ks_row.addWidget(self.reset_btn)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("background:#f8d7da;color:#842029;padding:6px;border-radius:4px;")
        self.error_label.hide()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Task", "Mode", "Status", "Updated"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()

        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(2000)
        self.log_pane.setFont(QFont("Consolas", 9))

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.log_pane)
        split.setSizes([300, 300])

        root = QVBoxLayout()
        root.addWidget(banner)
        root.addLayout(row)
        root.addWidget(self.stop_btn)
        root.addLayout(ks_row)
        root.addWidget(self.error_label)
        root.addWidget(split, 1)
        w = QWidget()
        w.setLayout(root)
        self.setCentralWidget(w)
        self._update_ks_label()

    def _append_log(self, text: str) -> None:
        self.log_pane.appendPlainText(f"{datetime.now():%H:%M:%S.%f}"[:-3] + "  " + text)

    def _alive_threads(self) -> list[threading.Thread]:
        return [t for t in self._threads if t.is_alive()]

    def _update_ks_label(self) -> None:
        if self.kill_switch.engaged:
            # Spec 11.6: say so when an action cannot be interrupted immediately.
            n = len(self._alive_threads())
            if n:
                self.ks_label.setText(f"Kill switch ENGAGED: stopping {n} task(s); waiting for the "
                                      f"current action to end. New tasks are blocked.")
            else:
                self.ks_label.setText("Kill switch ENGAGED: all tasks stopped; new tasks are blocked until reset.")
                self._ks_poll.stop()
            self.ks_label.setStyleSheet("color:#c62828;font-weight:bold;")
        else:
            self.ks_label.setText("Kill switch armed.")
            self.ks_label.setStyleSheet("color:#2e7d32;")
        self.reset_btn.setEnabled(self.kill_switch.engaged)

    def _refresh_tasks(self) -> None:
        tasks = self.store.list_tasks()
        self.table.setRowCount(len(tasks))
        for r, t in enumerate(tasks):
            vals = [str(t["id"]), t["title"], "dry-run" if t["dry_run"] else "live (simulated)",
                    t["status"], datetime.fromtimestamp(t["updated_at"]).strftime("%H:%M:%S")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 3 and v in _STATUS_COLORS:
                    item.setForeground(QColor(_STATUS_COLORS[v]))
                self.table.setItem(r, c, item)

    # --- actions -------------------------------------------------------------

    def start_task(self) -> int | None:
        title = self.task_input.text().strip() or "(untitled simulated task)"
        dry_run = self.dry_run_box.isChecked()
        actions = build_simulated_task(self.cfg, self.fail_box.isChecked())
        try:
            token = self.kill_switch.new_token()
        except KillSwitchEngaged as e:
            self._show_error(str(e))
            return None
        task_id = self.runner.create(title, actions, dry_run)
        executor = DryRunExecutor() if dry_run else RealExecutor()
        th = threading.Thread(target=self.runner.run, args=(task_id, actions, executor, token),
                              name=f"task-{task_id}", daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()] + [th]
        th.start()
        self.task_input.clear()
        self._refresh_tasks()
        return task_id

    def engage_kill_switch(self, source: str) -> None:
        self.kill_switch.engage(source)
        log.warning("kill switch engaged", extra={"event": {"kind": "kill_switch", "source": source}})
        self.store.add_event(None, "WARNING", "kill_switch", f"kill switch engaged via {source}")
        self._append_log(f"KILL SWITCH engaged via {source}")
        self._update_ks_label()
        if self._alive_threads():
            self._ks_poll.start()

    def reset_kill_switch(self) -> None:
        if self._alive_threads():
            self._show_error("Tasks are still stopping; reset again in a moment.")
            return
        self.kill_switch.reset()
        self.store.add_event(None, "INFO", "kill_switch", "kill switch reset by user")
        self._append_log("kill switch reset by user")
        self._update_ks_label()
        self.error_label.hide()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()
        self._append_log(f"ERROR: {text}")

    def _on_event(self, e: dict[str, Any]) -> None:
        if self._closed:  # events queued before close may arrive after the store is closed
            return
        self._append_log(f"[task {e['task_id']}] {e['level']:<7} {e['message']}")
        if e["kind"] in ("task_failed", "step_failed"):
            self._show_error(e["message"])
        self._refresh_tasks()

    # --- hotkey and lifecycle ------------------------------------------------

    def _register_hotkey(self) -> None:
        ok, msg = hotkey.register(int(self.winId()), self.cfg.kill_hotkey)
        self._hotkey_registered = ok
        log.log(logging.INFO if ok else logging.ERROR, msg,
                extra={"event": {"kind": "hotkey_registration", "ok": ok}})
        self.statusBar().showMessage(msg)
        self._append_log(msg)
        if not ok:
            self._show_error(f"{msg}. Use the STOP button.")

    def nativeEvent(self, eventType, message):  # noqa: N802 (Qt override)
        if eventType == b"windows_generic_MSG" and hotkey.is_kill_hotkey_message(int(message)):
            self.engage_kill_switch(f"hotkey {self.cfg.kill_hotkey}")
            return True, 0
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.kill_switch.engage("application closing")
        for t in self._threads:
            t.join(timeout=3)
        self._closed = True
        if self._hotkey_registered:
            hotkey.unregister(int(self.winId()))
        super().closeEvent(event)
