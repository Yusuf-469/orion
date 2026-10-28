"""Desktop shell: goal input (plan → validate → run), tool console, task list, live log,
kill switch, dry-run, resume of interrupted tasks, history controls."""

from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from orion.app import hotkey
from orion.app.confirm import QtConfirmer
from orion.config import OrionConfig
from orion.execution import Action, DryRunExecutor, RealExecutor
from orion.execution.runtime import ToolCall, ToolRuntime
from orion.execution.tool_action import tool_action
from orion.memory import TaskStore
from orion.orchestration.cancel import KillSwitch, KillSwitchEngaged
from orion.orchestration.graph_runner import GraphRunner
from orion.orchestration.runner import TaskRunner, simulated_action
from orion.orchestration.states import Status
from orion.planner.service import PlanResult, plan_request
from orion.planner.template import SUPPORTED_PHRASES, TemplatePlanner
from orion.policy import PolicyEngine
from orion.verification import Verifier
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
    from orion.tools.browser import browser_tools
    from orion.tools.documents import document_tools
    from orion.tools.windows.calculator import calculator_tools
    from orion.tools.windows.notepad import notepad_tools
    from orion.tools.windows.screen_click import screen_tools

    reg = ToolRegistry()
    for t in [*file_tools(), LaunchAppTool(), *notepad_tools(), *browser_tools(), *document_tools(),
              *calculator_tools(), *screen_tools()]:
        reg.register(t)
    return reg


DEMO_PAGES = Path(__file__).resolve().parents[3] / "demo" / "pages"

EXAMPLE_GOALS = [
    "save the table from sales.html as report.csv then summarize report.csv into summary.txt "
    "then open summary.txt in notepad",
    'type "Meeting moved to 4 pm" into summary.txt in notepad',
    'fill the form on signup.html with name "Asha Rao" email "asha@example.com" message "See you there"',
    "calculate 1250*12+300 in calculator",
    "click Export in the canvas demo",
    'create a file notes.txt containing "buy milk" then copy notes.txt to backup/notes.txt',
    "list files",
]


def install_demo_pages(workspace: Path) -> list[str]:
    """Copy demo pages into workspace/pages/ (only missing ones; never overwrites)."""
    added = []
    if DEMO_PAGES.is_dir():
        dest = workspace / "pages"
        dest.mkdir(parents=True, exist_ok=True)
        for f in DEMO_PAGES.glob("*.html"):
            if not (dest / f.name).exists():
                shutil.copyfile(f, dest / f.name)
                added.append(f.name)
    return added


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
    _planned = Signal(object)   # (request, PlanResult) from the planner thread

    def _make_planner(self):
        if self.cfg.planner == "llm":
            from orion.models.ollama import OllamaBackend
            from orion.planner.llm import LLMPlanner, output_schema
            backend = OllamaBackend(model=self.cfg.llm_model, schema=output_schema(), num_ctx=4096)
            return LLMPlanner(backend, self.registry, self.policy, self.cfg.workspace_dir)
        return TemplatePlanner()

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
        install_demo_pages(cfg.workspace_dir)
        self.registry = build_registry()
        self.confirmer = QtConfirmer(self)
        self.policy = PolicyEngine(frozenset(cfg.granted_permissions), cfg.confirm_reversible)
        self.tool_runtime = ToolRuntime(self.registry, self.policy, self.confirmer, cfg.workspace_dir)
        self.planner = self._make_planner()
        self.last_goal_task: int | None = None
        self._planned.connect(self._on_planned)
        from orion.recovery import RecoveryEngine
        self.graph = GraphRunner(store, self.kill_switch, self.tool_runtime, Verifier(cfg.workspace_dir),
                                 on_event=self._bridge.event.emit,
                                 recovery=RecoveryEngine(self.tool_runtime, self.confirmer))

        self.setWindowTitle("ORION")
        self.resize(1100, 760)
        self._build_ui()
        self._refresh_tasks()
        self._check_interrupted()
        if register_hotkey:
            self._register_hotkey()

    # --- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        granted = ", ".join(self.cfg.granted_permissions)
        banner = QLabel(
            f"ORION works only inside {self.cfg.workspace_dir.resolve()} and on local pages in its pages\\ folder. "
            f"Hover over the Goal box to see what it understands.  |  Allowed: {granted}")
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#fff3cd;color:#664d03;padding:6px;border-radius:4px;")

        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText(
            "Try: save the table from sales.html as report.csv then summarize report.csv into summary.txt "
            "then open summary.txt in notepad")
        self.goal_input.setToolTip("Supported phrases:\n" + "\n".join(SUPPORTED_PHRASES) +
                                   "\nChain clauses with 'then'.")
        self.goal_input.returnPressed.connect(self.start_goal)
        self.goal_btn = QPushButton("Plan && run")
        self.goal_btn.clicked.connect(self.start_goal)
        self.examples = QComboBox()
        self.examples.addItem("Examples…")
        for text in EXAMPLE_GOALS:
            self.examples.addItem(text)
        self.examples.setMaximumWidth(140)
        self.examples.activated.connect(self._use_example)
        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("Goal:"))
        goal_row.addWidget(self.goal_input, 1)
        goal_row.addWidget(self.examples)
        goal_row.addWidget(self.goal_btn)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("background:#e7f1ff;color:#084298;padding:6px;border-radius:4px;")
        self.info_label.hide()

        self.resume_label = QLabel()
        self.resume_label.setWordWrap(True)
        self.resume_label.setStyleSheet("background:#fff3cd;color:#664d03;padding:6px;border-radius:4px;")
        self.resume_btn = QPushButton("Resume (re-observe first)")
        self.resume_btn.clicked.connect(self.resume_interrupted)
        self.resume_row = QWidget()
        rr = QHBoxLayout(self.resume_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(self.resume_label, 1)
        rr.addWidget(self.resume_btn)
        self.resume_row.hide()

        self.delete_btn = QPushButton("Delete selected history")
        self.delete_btn.clicked.connect(self.delete_selected_history)
        self.clear_btn = QPushButton("Clear all history")
        self.clear_btn.clicked.connect(self.clear_history)
        hist_row = QHBoxLayout()
        hist_row.addStretch(1)
        hist_row.addWidget(self.delete_btn)
        hist_row.addWidget(self.clear_btn)

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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Task", "Mode", "Status", "Outcome", "Updated"])
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
        root.addWidget(self.resume_row)
        root.addLayout(mode_row)
        root.addLayout(goal_row)
        root.addLayout(tool_row)
        root.addLayout(row)
        root.addWidget(self.stop_btn)
        root.addLayout(ks_row)
        root.addWidget(self.info_label)
        root.addWidget(self.error_label)
        root.addWidget(split, 1)
        root.addLayout(hist_row)
        w = QWidget()
        w.setLayout(root)
        self.setCentralWidget(w)
        self._update_ks_label()

    def _use_example(self, index: int) -> None:
        if index > 0:
            self.goal_input.setText(self.examples.itemText(index))
            self.goal_input.setFocus()
        self.examples.setCurrentIndex(0)

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
            vals = [str(t["id"]), t["title"], "dry-run" if t["dry_run"] else "live", t["status"],
                    t.get("outcome") or "", datetime.fromtimestamp(t["updated_at"]).strftime("%H:%M:%S")]
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
        self._start_thread(f"task-{task_id}", self.runner.run, task_id, actions, executor, token)
        return task_id

    def _start_thread(self, name: str, fn, *args) -> None:
        th = threading.Thread(target=fn, args=args, name=name, daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()] + [th]
        th.start()
        self._refresh_tasks()

    def start_goal(self) -> int | None:
        """Plan the goal. Template plans are planned and started here (returns the task id).
        LLM plans are planned on a worker thread and need the user's review; returns None."""
        request = self.goal_input.text().strip()
        if not request:
            return None
        self.error_label.hide()
        self.info_label.hide()
        if self.planner.name != "template":
            self.goal_btn.setEnabled(False)
            self._show_info(f"Planning with the local model ({self.cfg.llm_model}); this can take ~10 s…")

            def work():
                try:
                    res = plan_request(self.planner, request, self.registry, self.policy, self.cfg.workspace_dir)
                except Exception as e:  # noqa: BLE001 - surface it in the UI
                    res = PlanResult("unsupported", None, None, [], f"planner error: {type(e).__name__}: {e}",
                                     self.planner.name)
                self._planned.emit((request, res))

            threading.Thread(target=work, name="planner", daemon=True).start()
            return None
        res = plan_request(self.planner, request, self.registry, self.policy, self.cfg.workspace_dir)
        return self._handle_plan(request, res)

    def _on_planned(self, payload) -> None:
        if self._closed:
            return
        self.goal_btn.setEnabled(True)
        self.info_label.hide()
        request, res = payload
        self.last_goal_task = self._handle_plan(request, res)

    def _review_plan(self, res: PlanResult) -> bool:
        """Mandatory review for model-made plans: show every step, path and text before anything runs."""
        lines = []
        for s in res.plan.steps:
            after = f"  (after {', '.join(s.depends_on)})" if s.depends_on else ""
            lines.append(f"{s.id}: {s.tool_id} {json.dumps(s.args, ensure_ascii=False)}{after}")
        warnings = [str(i) for i in res.issues if i.severity == "warning"]
        box = QMessageBox(QMessageBox.Question, "Review the plan before it runs",
                          f"The local model proposed {len(res.plan.steps)} step(s) for:\n\"{res.goal.request}\"\n\n"
                          + "\n".join(lines), QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText(
            "Files it may change: " + (", ".join(res.goal.authorized_outputs) or "none") +
            ("\nWarnings:\n" + "\n".join(warnings) if warnings else "") +
            "\n\nModels can misread requests. Run this plan?")
        box.setDefaultButton(QMessageBox.No)
        box.setObjectName("orion_plan_review")
        return box.exec() == QMessageBox.Yes

    def _handle_plan(self, request: str, res: PlanResult) -> int | None:
        self._append_log(f"planner '{res.planner}' -> {res.status}: {request}")
        if res.status == "clarify":
            self._show_info("ORION needs more information before planning:\n- " + "\n- ".join(res.questions) +
                            "\nRe-enter the goal with the details.")
            return None
        if res.status == "unsupported":
            self._show_error(res.message)
            return None
        for i in res.issues:
            self._append_log(f"  plan {i}")
        if res.status == "invalid":
            errs = [str(i) for i in res.issues if i.severity == "error"]
            self._show_error("Plan rejected by the validator:\n" + "\n".join(errs))
            return None
        if res.planner != "template" and not self._review_plan(res):
            self._append_log("plan declined by the user at review; nothing was run")
            self._show_info("Plan declined. Nothing was run.")
            return None
        dry_run = self.dry_run_box.isChecked()
        try:
            token = self.kill_switch.new_token()
        except KillSwitchEngaged as e:
            self._show_error(str(e))
            return None
        task_id = self.graph.create(res.goal, res.plan, res.planner, dry_run)
        self._start_thread(f"goal-{task_id}", self.graph.run, task_id, token, dry_run)
        self.goal_input.clear()
        return task_id

    def _check_interrupted(self) -> None:
        tasks = self.store.interrupted_tasks()
        if not tasks:
            self.resume_row.hide()
            return
        names = ", ".join(f"#{t['id']} {t['title']}" for t in tasks[:5])
        self.resume_label.setText(
            f"{len(tasks)} task(s) were interrupted (ORION closed or crashed mid-run): {names}. "
            f"Resume re-checks the environment first and never blindly repeats an uncertain action.")
        self.resume_row.show()

    def resume_interrupted(self) -> None:
        tasks = self.store.interrupted_tasks()
        try:
            token = self.kill_switch.new_token()
        except KillSwitchEngaged as e:
            self._show_error(str(e))
            return

        def work():
            for t in tasks:
                if token.is_cancelled:
                    break
                if self.store.load_plan(t["id"]) is None:
                    # Stage 1/2 tasks have no plan to resume from; close them honestly.
                    if t["status"] == "ready":
                        self.store.set_task_status(t["id"], Status.RUNNING)
                    self.store.set_task_status(t["id"], Status.CANCELLED, "interrupted; not resumable (no plan)")
                    self._bridge.event.emit({"task_id": t["id"], "level": "WARNING", "kind": "not_resumable",
                                             "message": f"task {t['id']} has no plan; marked cancelled"})
                    continue
                try:
                    self.graph.resume(t["id"], self.kill_switch.new_token())
                except Exception as e:  # noqa: BLE001 - surface it; never die silently
                    log.exception("resume failed", extra={"event": {"task_id": t["id"]}})
                    self._bridge.event.emit({"task_id": t["id"], "level": "ERROR", "kind": "task_failed",
                                             "message": f"resume of task {t['id']} failed: {type(e).__name__}: {e}"})
            self.kill_switch.release(token)

        self.resume_row.hide()
        self._start_thread("resume", work)

    def _ask_yes_no(self, title: str, text: str) -> bool:
        box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def delete_selected_history(self) -> None:
        if self._alive_threads():
            self._show_error("Wait for running tasks to finish before deleting history.")
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        ids = [int(self.table.item(r, 0).text()) for r in rows]
        if not ids:
            self._show_info("Select one or more tasks in the table first.")
            return
        if not self._ask_yes_no("Delete history", f"Permanently delete the stored history of task(s) {ids}? "
                                "Files in the workspace are not touched."):
            return
        for i in ids:
            self.store.delete_task(i)
        self._append_log(f"history deleted for task(s) {ids}")
        self._refresh_tasks()

    def clear_history(self) -> None:
        if self._alive_threads():
            self._show_error("Wait for running tasks to finish before clearing history.")
            return
        if not self._ask_yes_no("Clear all history", "Permanently delete ALL stored task history, plans and "
                                "events? Files in the workspace and the log file are not touched."):
            return
        n = self.store.delete_all_history()
        self.log_pane.clear()
        self._append_log(f"history cleared ({n} task(s) deleted)")
        self._refresh_tasks()

    def _show_info(self, text: str) -> None:
        self.info_label.setText(text)
        self.info_label.show()
        self._append_log(f"INFO: {text}")

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
        if e["kind"] in ("task_failed", "step_failed", "task_blocked", "resume_needs_review"):
            self._show_error(e["message"])
        elif e["kind"] == "task_outcome":
            if e.get("outcome") in ("verified_complete", "dry_run"):
                self._show_info(e["message"])
            else:
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
