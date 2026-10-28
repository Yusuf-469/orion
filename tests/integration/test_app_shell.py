"""UI shell tests. `ui` tests run offscreen; `real` tests open an ORION window on the desktop."""

import os
import time

import pytest

from orion.app import hotkey
from orion.config import OrionConfig
from orion.memory import TaskStore

pytestmark = [pytest.mark.ui, pytest.mark.mock]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


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
        cfg = OrionConfig(data_dir=tmp_path, workspace_dir=tmp_path / "workspace", simulated_steps=10,
                          simulated_step_seconds=0.3, **overrides)
        store = TaskStore(cfg.db_path)
        w = MainWindow(cfg, store, register_hotkey=False)
        w.show()
        made.append((w, store))
        return w

    yield make
    for w, store in made:
        w.close()
        store.close()


@pytest.fixture
def window(make_window):
    return make_window()


def test_parse_hotkey():
    assert hotkey.parse_hotkey("ctrl+alt+end") == (0x3, 0x23)
    assert hotkey.parse_hotkey("ctrl+shift+f12") == (0x6, 0x7B)
    for bad in ("end", "ctrl+", "hyper+x", "ctrl+nokey"):
        with pytest.raises(ValueError):
            hotkey.parse_hotkey(bad)


def test_ui_responsive_during_task_and_stop_within_2s(qapp, window):
    from PySide6.QtCore import QElapsedTimer, QTimer

    window.dry_run_box.setChecked(False)
    window.task_input.setText("responsiveness check")
    tid = window.start_task()
    assert tid is not None

    # Measure the worst gap between 20 ms timer ticks while the task runs.
    gaps, clock, last = [], QElapsedTimer(), [0]
    clock.start()

    def tick():
        now = clock.elapsed()
        gaps.append(now - last[0])
        last[0] = now

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(20)
    _pump(qapp, 1.0)
    timer.stop()
    assert max(gaps[1:]) < 250, f"UI stalled for {max(gaps)} ms"

    t0 = time.monotonic()
    window.stop_btn.click()
    stopped = _pump(qapp, 2.0, until=lambda: window.store.get_task(tid)["status"] == "cancelled"
                    and f"task {tid} cancelled" in window.log_pane.toPlainText())
    assert stopped, "task not cancelled and shown in the log within 2 s"
    print(f"\n[S5 mock/ui] STOP button -> cancelled and visible in {(time.monotonic() - t0) * 1000:.0f} ms; "
          f"max UI gap {max(gaps[1:])} ms")
    assert window.kill_switch.engaged and window.reset_btn.isEnabled()


def test_uninterruptible_action_reported_honestly(qapp, window, monkeypatch):
    """Spec 11.6: if the current action cannot be interrupted, the UI must say so."""
    from orion.app import main_window as mw
    from orion.execution import Action

    def stubborn(token):
        time.sleep(0.8)  # ignores the token on purpose
        return "slept 0.8s"

    monkeypatch.setattr(mw, "build_simulated_task", lambda cfg, fail: [Action("stubborn", stubborn)] * 3)
    window.dry_run_box.setChecked(False)
    tid = window.start_task()
    _pump(qapp, 0.2)
    window.stop_btn.click()
    assert "stopping 1 task" in window.ks_label.text()
    assert _pump(qapp, 3.0, until=lambda: "all tasks stopped" in window.ks_label.text())
    assert window.store.get_task(tid)["status"] == "cancelled"
    # the in-flight action finished; the remaining two never started
    assert [s["status"] for s in window.store.list_steps(tid)] == ["succeeded", "cancelled", "cancelled"]


def test_engaged_switch_blocks_new_task_visibly(qapp, window):
    window.engage_kill_switch("test")
    assert window.start_task() is None
    assert not window.error_label.isHidden()
    window.reset_kill_switch()
    assert not window.kill_switch.engaged


def test_dry_run_default_on_and_executes_nothing(qapp, window):
    assert window.dry_run_box.isChecked()
    tid = window.start_task()
    assert _pump(qapp, 3.0, until=lambda: window.store.get_task(tid)["status"] == "skipped")
    assert all(s["started_at"] is None for s in window.store.list_steps(tid))


def test_injected_failure_is_visible(qapp, window):
    window.dry_run_box.setChecked(False)
    window.fail_box.setChecked(True)
    window.cfg = window.cfg.model_copy(update={"simulated_step_seconds": 0.01})
    tid = window.start_task()
    assert _pump(qapp, 3.0, until=lambda: window.store.get_task(tid)["status"] == "failed")
    _pump(qapp, 0.1)
    assert "injected test failure" in window.error_label.text()


@pytest.mark.real
@pytest.mark.skipif(os.environ.get("QT_QPA_PLATFORM") == "offscreen", reason="needs a real window handle")
def test_real_hotkey_registration_and_wm_hotkey_handling(qapp, tmp_path):
    """Registers the real global hotkey, then posts WM_HOTKEY to our own window.

    This checks OS registration and our message handling. It does NOT press keys
    on the desktop; pressing the physical hotkey stays a manual check.
    """
    import ctypes
    from orion.app.main_window import MainWindow

    cfg = OrionConfig(data_dir=tmp_path, workspace_dir=tmp_path / "workspace")
    store = TaskStore(cfg.db_path)
    w = MainWindow(cfg, store, register_hotkey=True)
    w.show()
    _pump(qapp, 0.2)
    try:
        if not w._hotkey_registered and "1409" in w.statusBar().currentMessage():
            # Win32 1409 = hotkey already registered, e.g. by an ORION window that is already running.
            pytest.skip("Ctrl+Alt+End is held by another running program (likely an open ORION window)")
        assert w._hotkey_registered, w.statusBar().currentMessage()
        ctypes.windll.user32.PostMessageW(int(w.winId()), hotkey.WM_HOTKEY, hotkey.HOTKEY_ID, 0)
        assert _pump(qapp, 1.0, until=lambda: w.kill_switch.engaged)
    finally:
        w.close()
        store.close()
