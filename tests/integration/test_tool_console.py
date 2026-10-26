"""Tool console and confirmation dialog, offscreen. File effects stay in pytest's tmp workspace."""

import json
import time

import pytest

from orion.config import OrionConfig
from orion.memory import TaskStore
from orion.tools import Permission

pytestmark = [pytest.mark.ui, pytest.mark.safety]

WITH_DELETE = tuple(Permission)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def _pump(qapp, seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if until and until():
            return True
        time.sleep(0.005)
    return bool(until and until())


@pytest.fixture
def make_window(qapp, tmp_path):
    from orion.app.main_window import MainWindow
    made = []

    def make(**overrides):
        cfg = OrionConfig(data_dir=tmp_path, workspace_dir=tmp_path / "workspace", dry_run_default=False,
                          **overrides)
        store = TaskStore(cfg.db_path)
        w = MainWindow(cfg, store, register_hotkey=False)
        w.show()
        made.append((w, store))
        return w

    yield make
    for w, store in made:
        w.close()
        store.close()


def run_tool(qapp, w, tool_id, args, until_status=("succeeded", "failed", "blocked", "cancelled", "skipped")):
    w.tool_combo.setCurrentText(tool_id)
    w.tool_args.setText(json.dumps(args))
    tid = w.start_tool()
    assert tid is not None
    _pump(qapp, 5, until=lambda: w.store.get_task(tid)["status"] in until_status)
    return tid, w.store.get_task(tid)


def _dialog(w):
    from PySide6.QtWidgets import QMessageBox
    box = w.findChild(QMessageBox, "orion_confirm")
    return box if box is not None and box.isVisible() else None


def test_write_new_via_console_creates_verified_file(qapp, make_window):
    w = make_window()
    _, task = run_tool(qapp, w, "files.write_new", {"path": "hello.txt", "content": "hi"})
    assert task["status"] == "succeeded"
    assert (w.cfg.workspace_dir / "hello.txt").read_text() == "hi"
    step = w.store.list_steps(task["id"])[0]
    assert "re-read sha256" in step["evidence"] and not step["evidence"].startswith("simulated")


def test_dry_run_tool_writes_nothing_but_shows_policy(qapp, make_window):
    w = make_window()
    w.dry_run_box.setChecked(True)
    _, task = run_tool(qapp, w, "files.write_new", {"path": "x.txt", "content": "1"})
    assert task["status"] == "skipped" and not (w.cfg.workspace_dir / "x.txt").exists()
    assert "would allow" in w.store.list_steps(task["id"])[0]["evidence"]


def test_delete_without_permission_is_blocked_and_visible(qapp, make_window):
    w = make_window()   # default permissions: no files.delete
    (w.cfg.workspace_dir / "keep.txt").write_text("1")
    _, task = run_tool(qapp, w, "files.delete", {"path": "keep.txt"})
    _pump(qapp, 0.2)
    assert task["status"] == "blocked" and (w.cfg.workspace_dir / "keep.txt").exists()
    assert "permission_denied" in w.error_label.text()


def test_out_of_workspace_path_blocked(qapp, make_window):
    w = make_window()
    _, task = run_tool(qapp, w, "files.write_new", {"path": "..\\escape.txt", "content": "x"})
    assert task["status"] == "blocked"
    assert not (w.cfg.workspace_dir.parent / "escape.txt").exists()


@pytest.mark.parametrize("answer,expect_status,file_kept", [("yes", "succeeded", False), ("no", "blocked", True)])
def test_delete_confirmation_dialog(qapp, make_window, answer, expect_status, file_kept):
    from PySide6.QtWidgets import QMessageBox
    w = make_window(granted_permissions=WITH_DELETE)
    target = w.cfg.workspace_dir / "x.txt"
    target.write_text("data")
    w.tool_combo.setCurrentText("files.delete")
    w.tool_args.setText(json.dumps({"path": "x.txt"}))
    tid = w.start_tool()
    assert _pump(qapp, 3, until=lambda: _dialog(w) is not None), "no confirmation dialog appeared"
    box = _dialog(w)
    assert "x.txt" in box.text() and "this one action only" in box.informativeText()
    assert box.defaultButton() is box.button(QMessageBox.No)
    box.button(QMessageBox.Yes if answer == "yes" else QMessageBox.No).click()
    _pump(qapp, 3, until=lambda: w.store.get_task(tid)["status"] == expect_status)
    assert w.store.get_task(tid)["status"] == expect_status
    assert target.exists() is file_kept


def test_second_confirmation_gets_a_fresh_dialog(qapp, make_window):
    """Regression (found by the real-window acceptance run): an answered dialog stayed as a hidden
    child, so the next confirmation could not be found and dialogs leaked."""
    from PySide6.QtWidgets import QMessageBox
    w = make_window(granted_permissions=WITH_DELETE)
    for name in ("a.txt", "b.txt"):
        (w.cfg.workspace_dir / name).write_text("x")
        w.tool_combo.setCurrentText("files.delete")
        w.tool_args.setText(json.dumps({"path": name}))
        tid = w.start_tool()
        assert _pump(qapp, 3, until=lambda: _dialog(w) is not None)
        _dialog(w).button(QMessageBox.No).click()
        assert _pump(qapp, 3, until=lambda: w.store.get_task(tid)["status"] == "blocked")
        _pump(qapp, 0.1)
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert w.findChildren(QMessageBox) == []


def test_kill_switch_closes_open_dialog_and_nothing_runs(qapp, make_window):
    w = make_window(granted_permissions=WITH_DELETE)
    target = w.cfg.workspace_dir / "x.txt"
    target.write_text("data")
    w.tool_combo.setCurrentText("files.delete")
    w.tool_args.setText(json.dumps({"path": "x.txt"}))
    tid = w.start_tool()
    assert _pump(qapp, 3, until=lambda: _dialog(w) is not None)
    w.stop_btn.click()
    assert _pump(qapp, 2, until=lambda: w.store.get_task(tid)["status"] == "cancelled")
    _pump(qapp, 0.2)
    assert _dialog(w) is None and target.exists()


def test_invalid_json_args_rejected_without_task(qapp, make_window):
    w = make_window()
    w.tool_combo.setCurrentText("files.read")
    for bad in ("{not json", "[1, 2]"):
        w.tool_args.setText(bad)
        assert w.start_tool() is None
        assert "invalid tool arguments" in w.error_label.text()
    assert w.store.list_tasks() == []
