"""Desktop shell: task input, tool console, task list, live log, kill switch, dry-run."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from orion.app import hotkey
from orion.app.confirm import QtConfirmer
from orion.config import OrionConfig
from orion.execution import Action, DryRunExecutor, RealExecutor
from orion.execution.runtime import ToolCall, ToolRuntime
from orion.execution.tool_action import tool_action
from orion.memory import TaskStore
from orion.orchestration.cancel import KillSwitch, KillSwitchEngaged
from orion.orchestration.runner import TaskRunner, simulated_action
from orion.policy import PolicyEngine
from orion.tools import ToolRegistry
from orion.tools.files import file_tools
from orion.tools.windows.launch import LaunchAppTool

log = logging.getLogger("orion.app")

_STATUS_COLORS = {
    "running": "#1565c0", "succeeded": "#2e7d32", "failed": "#c62828",
    "cancelled": "#ef6c00", "skipped": "#6a1b9a", "blocked": "#ad6800", "needs_review": "#c62828",
}

TOOL_EXAMPLES: dict[str, dict[str, Any]] = {
    "files.list": {"path": "."},
    "files.read": {"path": "hello.txt"},
    "files.write_new": {"path": "hello.txt", "content": "Hello from ORION"},
    "files.copy": {"src": "hello.txt", "dst": "hello_copy.txt"},
    "files.delete": {"path": "hello_copy.txt"},
    "app.launch": {"app": "notepad"},
}


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for t in [*file_tools(), LaunchAppTool()]:
        reg.register(t)
    return reg


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

        cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.registry = build_registry()
        self.confirmer = QtConfirmer(self)
        self.policy = PolicyEngine(frozenset(cfg.granted_permissions), cfg.confirm_reversible)
        self.tool_runtime = ToolRuntime(self.registry, self.policy, self.confirmer, cfg.workspace_dir)

        self.setWindowTitle("ORION (Stage 2)")
        self.resize(1000, 700)
        self._build_ui()
        self._refresh_tasks()
        if register_hotkey:
            self._register_hotkey()

    # --- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        granted = ", ".join(self.cfg.granted_permissions)
        banner = QLabel(
            f"Stage 2: goals are not interpreted yet. Use the tool console to run one registered tool, "
            f"or run a simulated task. Files are confined to: {self.cfg.workspace_dir.resolve()}  |  "
            f"Granted: {granted}")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#fff3cd;color:#664d03;padding:6px;border-radius:4px;")

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Simulated task title (text is recorded, not interpreted)")
        self.task_input.returnPressed.connect(self.start_task)
        self.dry_run_box = QCheckBox("Dry run (plan only, execute nothing)")
        self.dry_run_box.setChecked(self.cfg.dry_run_default)
        self.fail_box = QCheckBox("Inject failure at step 5")
        self.run_btn = QPushButton("Run simulated")
        self.run_btn.clicked.connect(self.start_task)

        row = QHBoxLayout()
        row.addWidget(self.task_input, 1)
        row.addWidget(self.fail_box)
        row.addWidget(self.run_btn)

        self.tool_combo = QComboBox()
        for spec in self.registry.specs():
            self.tool_combo.addItem(spec.id)
            self.tool_combo.setItemData(
                self.tool_combo.count() - 1,
                f"{spec.description}\nside effect: {spec.side_effect}\n"
                f"needs: {', '.join(sorted(spec.permissions)) or 'nothing'}", Qt.ToolTipRole)
        self.tool_args = QLineEdit()
        self.tool_args.setFont(QFont("Consolas", 9))
        self.tool_combo.currentTextChanged.connect(
            lambda tid: self.tool_args.setText(json.dumps(TOOL_EXAMPLES.get(tid, {}))))
        self.tool_combo.setCurrentIndex(self.tool_combo.findText("files.list"))
        self.tool_args.setText(json.dumps(TOOL_EXAMPLES["files.list"]))
        self.tool_args.returnPressed.connect(self.start_tool)
        self.tool_btn = QPushButton("Run tool")
        self.tool_btn.clicked.connect(self.start_tool)
        tool_row = QHBoxLayout()
        tool_row.addWidget(QLabel("Tool:"))
        tool_row.addWidget(self.tool_combo)
        tool_row.addWidget(QLabel("Args (JSON):"))
        tool_row.addWidget(self.tool_args, 1)
        tool_row.addWidget(self.tool_btn)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.dry_run_box)
        mode_row.addStretch(1)

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
        root.addLayout(mode_row)
        root.addLayout(tool_row)
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
            vals = [str(t["id"]), t["title"], "dry-run" if t["dry_run"] else "live",
                    t["status"], datetime.fromtimestamp(t["updated_at"]).strftime("%H:%M:%S")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 3 and v in _STATUS_COLORS:
                    item.setForeground(QColor(_STATUS_COLORS[v]))
                self.table.setItem(r, c, item)

    # --- actions -------------------------------------------------------------

    def start_task(self) -> int | None:
        title = "[simulated] " + (self.task_input.text().strip() or "untitled")
        actions = build_simulated_task(self.cfg, self.fail_box.isChecked())
        task_id = self._launch(title, actions)
        if task_id is not None:
            self.task_input.clear()
        return task_id

    def start_tool(self) -> int | None:
        tool_id = self.tool_combo.currentText()
        try:
            args = json.loads(self.tool_args.text() or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            call = ToolCall(tool_id=tool_id, args=args)
        except (ValueError, ValidationError) as e:
            self._show_error(f"invalid tool arguments: {e}")
            return None
        return self._launch(f"[tool] {tool_id}", [tool_action(self.tool_runtime, call)])

    def _launch(self, title: str, actions: list[Action]) -> int | None:
        dry_run = self.dry_run_box.isChecked()
        try:
            token = self.kill_switch.new_token()
        except KillSwitchEngaged as e:
            self._show_error(str(e))
            return None
        self.error_label.hide()
        task_id = self.runner.create(title, actions, dry_run)
        executor = DryRunExecutor() if dry_run else RealExecutor()
        th = threading.Thread(target=self.runner.run, args=(task_id, actions, executor, token),
                              name=f"task-{task_id}", daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()] + [th]
        th.start()
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
        if e["kind"] in ("task_failed", "step_failed", "task_blocked"):
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
