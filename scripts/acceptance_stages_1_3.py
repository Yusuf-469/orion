"""Scripted acceptance run of the Stage 1-3 manual checklists in REAL windows.

This is automated: it clicks ORION's own widgets through Qt, posts WM_HOTKEY to
ORION's own window, launches and closes Calculator, and crashes a real
subprocess. It never presses keys on the desktop and never touches the user's
workspace: data and workspace live in a fresh temp folder.

usage: python scripts/acceptance_stages_1_3.py [--out artifacts/acceptance_<date>.json]
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from orion.app import hotkey
from orion.app.main_window import MainWindow
from orion.config import OrionConfig
from orion.memory import TaskStore
from orion.observability import setup_logging
from orion.tools import Permission
from orion.tools.files import TRASH_DIR
from orion.tools.windows.launch import ALLOWLIST, _matches
from orion.tools.windows.win32 import post_close, visible_windows

ROOT = Path(__file__).resolve().parent.parent
app = QApplication.instance() or QApplication(sys.argv[:1])
results: list[dict] = []


def pump(seconds: float, until=None) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return bool(until and until())


def check(cid: str, what: str):
    def deco(fn):
        t0 = time.monotonic()
        try:
            evidence = fn() or ""
            results.append({"id": cid, "check": what, "result": "passed", "evidence": evidence,
                            "seconds": round(time.monotonic() - t0, 2)})
            print(f"PASS {cid}: {what}")
        except Exception as e:  # noqa: BLE001
            results.append({"id": cid, "check": what, "result": "failed",
                            "evidence": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]})
            print(f"FAIL {cid}: {what}: {e}")
        return fn
    return deco


class Env:
    def __init__(self, base: Path):
        self.base = base
        self.windows: list[tuple[MainWindow, TaskStore]] = []

    def window(self, *, dry_run=False, granted=None, hotkey_on=False, steps=10, step_s=0.3) -> MainWindow:
        cfg = OrionConfig(data_dir=self.base / "data", workspace_dir=self.base / "workspace",
                          dry_run_default=dry_run, simulated_steps=steps, simulated_step_seconds=step_s,
                          **({"granted_permissions": granted} if granted else {}))
        store = TaskStore(cfg.db_path)
        w = MainWindow(cfg, store, register_hotkey=hotkey_on)
        w.show()
        pump(0.2)
        self.windows.append((w, store))
        return w

    def close_all(self):
        for w, s in self.windows:
            w.close()
            s.close()
        self.windows.clear()
        pump(0.2)

    @property
    def ws(self) -> Path:
        return self.base / "workspace"


def run_tool(w: MainWindow, tool: str, args: dict, timeout=6.0) -> dict:
    w.tool_combo.setCurrentText(tool)
    w.tool_args.setText(json.dumps(args))
    tid = w.start_tool()
    assert tid is not None, f"no task created: {w.error_label.text()}"
    assert pump(timeout, until=lambda: w.store.get_task(tid)["status"] in
                ("succeeded", "failed", "blocked", "cancelled", "skipped")), "task did not finish"
    pump(0.1)
    t = w.store.get_task(tid)
    t["step"] = w.store.list_steps(tid)[0]
    return t


def run_goal(w: MainWindow, text: str, timeout=8.0) -> dict | None:
    w.goal_input.setText(text)
    tid = w.start_goal()
    if tid is None:
        return None
    assert pump(timeout, until=lambda: w.store.get_task(tid)["outcome"] is not None), "goal did not finish"
    pump(0.1)
    t = w.store.get_task(tid)
    t["steps"] = w.store.list_steps(tid)
    return t


def dialog(w: MainWindow):
    box = w.findChild(QMessageBox, "orion_confirm")
    return box if box is not None and box.isVisible() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    base = Path(tempfile.mkdtemp(prefix="orion_accept_"))
    setup_logging(base / "data" / "logs")
    env = Env(base)
    WITH_DELETE = tuple(Permission)

    # ---------------- Stage 1 ----------------
    @check("S1-M2", "dry-run default on; simulated task ends skipped with 0 executed")
    def _():
        w = env.window(dry_run=True)
        assert w.dry_run_box.isChecked()
        tid = w.start_task()
        assert pump(6, until=lambda: w.store.get_task(tid)["status"] == "skipped")
        steps = w.store.list_steps(tid)
        assert all(s["started_at"] is None for s in steps)
        return f"task {tid} skipped; {len(steps)} steps planned, 0 started"

    @check("S1-M3/M4", "live simulated task runs; STOP cancels within 2 s; UI responsive")
    def _():
        w = env.window()
        tid = w.start_task()
        gaps, last = [], [time.monotonic()]

        def tick():
            now = time.monotonic()
            gaps.append(now - last[0])
            last[0] = now
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            app.processEvents()
            tick()
            time.sleep(0.01)
        t0 = time.monotonic()
        w.stop_btn.click()
        assert pump(2.0, until=lambda: w.store.get_task(tid)["status"] == "cancelled"), "not cancelled in 2 s"
        ms = (time.monotonic() - t0) * 1000
        return f"cancelled {ms:.0f} ms after STOP; worst UI loop gap {max(gaps) * 1000:.0f} ms"

    @check("S1-M5/M6", "engaged switch blocks new tasks visibly; reset re-enables")
    def _():
        w = env.windows[-1][0]
        assert w.kill_switch.engaged and w.start_task() is None
        assert "kill switch engaged" in w.error_label.text()
        pump(0.5)
        w.reset_kill_switch()
        assert not w.kill_switch.engaged
        tid = w.start_task()
        assert tid is not None
        w.stop_btn.click()
        pump(2, until=lambda: w.store.get_task(tid)["status"] == "cancelled")
        pump(0.5)
        w.reset_kill_switch()
        return "blocked while engaged; task started after reset"

    @check("S1-M8", "injected failure shows red banner and task failed")
    def _():
        w = env.window(step_s=0.01)
        w.fail_box.setChecked(True)
        tid = w.start_task()
        assert pump(4, until=lambda: w.store.get_task(tid)["status"] == "failed")
        pump(0.1)
        assert "injected test failure" in w.error_label.text() and w.error_label.isVisible()
        return w.error_label.text()[:120]

    @check("S1-M11", "closing during a live task exits within 3 s and leaves the task cancelled")
    def _():
        w, s = env.window(), None
        tid = w.start_task()
        pump(0.4)
        t0 = time.monotonic()
        w.close()
        dt = time.monotonic() - t0
        status = w.store.get_task(tid)["status"]
        assert dt < 3.5 and status == "cancelled", (dt, status)
        return f"closed in {dt:.2f} s; task {status}"
    env.close_all()

    # ---------------- Stage 2 ----------------
    w = env.window()

    @check("T1", "files.write_new creates a verified file")
    def _():
        t = run_tool(w, "files.write_new", {"path": "hello.txt", "content": "Hello from ORION"})
        assert t["status"] == "succeeded" and "matches" in t["step"]["evidence"]
        assert (env.ws / "hello.txt").read_text() == "Hello from ORION"
        return t["step"]["evidence"]

    @check("T2", "write_new never overwrites")
    def _():
        t = run_tool(w, "files.write_new", {"path": "hello.txt", "content": "different"})
        assert t["status"] == "failed" and "never overwrites" in t["step"]["evidence"]
        assert (env.ws / "hello.txt").read_text() == "Hello from ORION"
        return t["step"]["evidence"]

    @check("T3", "files.read reads 16 bytes")
    def _():
        t = run_tool(w, "files.read", {"path": "hello.txt"})
        assert t["status"] == "succeeded" and "read 16 bytes" in t["step"]["evidence"]
        return t["step"]["evidence"]

    @check("T4", "path escape is blocked and nothing is written outside")
    def _():
        t = run_tool(w, "files.write_new", {"path": "..\\escape.txt", "content": "x"})
        assert t["status"] == "blocked" and "permission_denied" in t["step"]["evidence"]
        assert not (env.base / "escape.txt").exists()
        return t["step"]["evidence"]

    @check("T5", "copy succeeds; delete blocked without files.delete")
    def _():
        c = run_tool(w, "files.copy", {"src": "hello.txt", "dst": "hello_copy.txt"})
        d = run_tool(w, "files.delete", {"path": "hello_copy.txt"})
        assert c["status"] == "succeeded" and d["status"] == "blocked" and (env.ws / "hello_copy.txt").exists()
        return d["step"]["evidence"]
    env.close_all()

    w = env.window(granted=WITH_DELETE)

    @check("T6", "delete asks (default No); No keeps file; Yes moves it to trash")
    def _():
        out = []
        for answer in ("no", "yes"):
            w.tool_combo.setCurrentText("files.delete")
            w.tool_args.setText(json.dumps({"path": "hello_copy.txt"}))
            tid = w.start_tool()
            assert pump(4, until=lambda: dialog(w) is not None), "no dialog"
            box = dialog(w)
            assert "hello_copy.txt" in box.text() and TRASH_DIR in box.informativeText()
            assert box.defaultButton() is box.button(QMessageBox.No)
            box.button(QMessageBox.Yes if answer == "yes" else QMessageBox.No).click()
            want = "succeeded" if answer == "yes" else "blocked"
            assert pump(4, until=lambda: w.store.get_task(tid)["status"] == want)
            out.append(f"{answer}->{want}")
        assert not (env.ws / "hello_copy.txt").exists()
        assert any(p.name.endswith("hello_copy.txt") for p in (env.ws / TRASH_DIR).iterdir())
        return ", ".join(out) + "; file now in trash"
    env.close_all()

    @check("T7", "kill hotkey (WM_HOTKEY to ORION's window) closes an open dialog; task cancelled; file kept")
    def _():
        w = env.window(granted=WITH_DELETE, hotkey_on=True)
        assert w._hotkey_registered, "hotkey registration failed (is another ORION running?)"
        (env.ws / "keep.txt").write_text("keep")
        w.tool_combo.setCurrentText("files.delete")
        w.tool_args.setText(json.dumps({"path": "keep.txt"}))
        tid = w.start_tool()
        assert pump(4, until=lambda: dialog(w) is not None)
        ctypes.windll.user32.PostMessageW(int(w.winId()), hotkey.WM_HOTKEY, hotkey.HOTKEY_ID, 0)
        assert pump(3, until=lambda: w.store.get_task(tid)["status"] == "cancelled")
        pump(0.3)
        assert dialog(w) is None and (env.ws / "keep.txt").exists()
        w.reset_kill_switch()
        return "dialog closed, task cancelled, keep.txt intact"
    env.close_all()

    w = env.window()

    @check("T8", "app.launch calculator verified by a new window (closed afterwards)")
    def _():
        if any(_matches(ALLOWLIST["calculator"], x) for x in visible_windows()):
            raise RuntimeError("SKIPPED: a Calculator window is already open")
        before = {x.hwnd for x in visible_windows()}
        t = run_tool(w, "app.launch", {"app": "calculator"}, timeout=20)
        new = [x for x in visible_windows() if x.hwnd not in before and _matches(ALLOWLIST["calculator"], x)]
        for x in new:
            post_close(x.hwnd)
        assert t["status"] == "succeeded" and "new window 'Calculator'" in t["step"]["evidence"]
        return t["step"]["evidence"]

    @check("T9", "dry-run tool shows policy, creates nothing")
    def _():
        w.dry_run_box.setChecked(True)
        t = run_tool(w, "files.write_new", {"path": "dry.txt", "content": "x"})
        w.dry_run_box.setChecked(False)
        assert t["status"] == "skipped" and "would allow" in t["step"]["evidence"]
        assert not (env.ws / "dry.txt").exists()
        return t["step"]["evidence"]

    # ---------------- Stage 3 ----------------
    G = "create a file notes.txt containing hello then copy notes.txt to backup/notes.txt"

    @check("G1", "dry-run goal previews both steps, creates nothing")
    def _():
        w.dry_run_box.setChecked(True)
        t = run_goal(w, G)
        w.dry_run_box.setChecked(False)
        assert t["outcome"] == "dry_run" and all("would allow" in s["evidence"] for s in t["steps"])
        assert not (env.ws / "notes.txt").exists()
        return f"{len(t['steps'])} steps previewed"

    @check("G2", "live goal is verified_complete with correct content")
    def _():
        t = run_goal(w, G)
        assert t["outcome"] == "verified_complete", t["outcome"]
        assert (env.ws / "backup" / "notes.txt").read_text() == "hello"
        return t["steps"][-1]["evidence"][:160]

    @check("G3", "missing info -> clarifying question, no task")
    def _():
        n = len(w.store.list_tasks())
        assert run_goal(w, "copy notes.txt") is None and len(w.store.list_tasks()) == n
        assert "Where should the copy" in w.info_label.text()
        return w.info_label.text().splitlines()[1]

    @check("G4", "unsupported request is refused, not guessed")
    def _():
        assert run_goal(w, "send an email to my boss") is None
        assert "does not understand" in w.error_label.text()
        return w.error_label.text()[:100]

    @check("G5", "escape path -> plan rejected before anything runs")
    def _():
        assert run_goal(w, "create a file ..\\x.txt containing y") is None
        assert "Plan rejected" in w.error_label.text() and "outside_workspace" in w.error_label.text()
        assert not (env.base / "x.txt").exists()
        return "rejected: outside_workspace"

    @check("G6a", "move with default permissions -> plan rejected (delete not granted), nothing runs")
    def _():
        assert run_goal(w, "move notes.txt to archive/notes.txt") is None
        assert "permission_denied" in w.error_label.text()
        assert not (env.ws / "archive").exists()
        return "rejected: permission_denied"

    @check("G7", "goal without completion checks is 'unverified', not success")
    def _():
        t = run_goal(w, "list files")
        assert t["outcome"] == "unverified" and t["status"] == "needs_review"
        return "outcome unverified"
    env.close_all()

    @check("G6b", "move with delete granted but declined -> partially_complete, source kept")
    def _():
        w = env.window(granted=WITH_DELETE)
        w.goal_input.setText("move notes.txt to archive/notes.txt")
        tid = w.start_goal()
        assert pump(5, until=lambda: dialog(w) is not None), "no dialog"
        dialog(w).button(QMessageBox.No).click()
        assert pump(5, until=lambda: w.store.get_task(tid)["outcome"] is not None)
        t = w.store.get_task(tid)
        assert t["outcome"] == "partially_complete", t["outcome"]
        assert (env.ws / "notes.txt").exists() and (env.ws / "archive" / "notes.txt").exists()
        return "copy done, delete blocked, outcome partially_complete"
    env.close_all()

    @check("G8/G9", "real crash mid-copy -> banner on start -> Resume verifies, does not repeat")
    def _():
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "_crash_copy.py"), str(base / "data"),
                            str(env.ws)], capture_output=True, text=True, timeout=60)
        assert p.returncode == 3, (p.returncode, p.stdout, p.stderr[-500:])
        w = env.window()
        assert w.resume_row.isVisible() and "interrupted" in w.resume_label.text()
        [task] = w.store.interrupted_tasks()
        w.resume_btn.click()
        assert pump(8, until=lambda: w.store.get_task(task["id"])["outcome"] is not None)
        t = w.store.get_task(task["id"])
        s2 = [s for s in w.store.list_steps(task["id"]) if s["step_key"] == "s2"][0]
        assert t["outcome"] == "verified_complete" and s2["evidence"].startswith("verified after resume")
        return f"subprocess exit 3; {s2['evidence'][:120]}"

    @check("G10", "history: delete selected (Yes) removes one row; clear all (No) keeps the rest; files untouched")
    def _():
        w = env.windows[-1][0]
        files_before = sorted(p.name for p in env.ws.rglob("*"))
        n = len(w.store.list_tasks())
        w._ask_yes_no = lambda *a: True       # stands in for clicking "Yes"
        w.table.selectRow(0)
        w.delete_selected_history()
        assert len(w.store.list_tasks()) == n - 1
        w._ask_yes_no = lambda *a: False      # stands in for clicking "No"
        w.clear_history()
        assert len(w.store.list_tasks()) == n - 1
        assert sorted(p.name for p in env.ws.rglob("*")) == files_before
        return f"{n} -> {n - 1} tasks; clear declined; workspace unchanged"
    env.close_all()

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "src"], capture_output=True, text=True,
                                cwd=ROOT).stdout.strip())
    report = {
        "kind": "automated acceptance run in real windows (scripted clicks; not a human run)",
        "run_at": datetime.now(timezone.utc).isoformat(), "git_commit": commit, "src_dirty": dirty,
        "temp_base": str(base), "passed": sum(r["result"] == "passed" for r in results),
        "failed": sum(r["result"] == "failed" for r in results), "results": results,
    }
    text = json.dumps(report, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(f"\n{report['passed']} passed, {report['failed']} failed (commit {commit}{', src dirty' if dirty else ''})")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
