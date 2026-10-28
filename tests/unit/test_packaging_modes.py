"""Startup modes used by the packaged build (helpers allowlist, resource paths, self-test report)."""

import json
import sys

import pytest

from orion import resources
from orion.app import main as entry


def test_resources_point_at_the_repository_from_source():
    assert not resources.FROZEN
    assert (resources.path("demo", "pages") / "sales.html").exists()
    cmd = resources.helper_command("demo/apps/canvas_buttons.py", "x.log")
    assert cmd[1].endswith("canvas_buttons.py") and cmd[-1] == "x.log"


@pytest.mark.parametrize("name", ["..\\..\\evil.py", "C:/Windows/System32/cmd.exe", "demo/apps/other.py"])
def test_run_helper_refuses_anything_not_allowlisted(name, capsys):
    assert entry.main(["--run-helper", name]) == 2
    assert "unknown helper" in capsys.readouterr().err


def test_packaged_mode_helpers_go_through_the_exe(monkeypatch):
    monkeypatch.setattr(resources, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\ORION\ORION.exe")
    assert resources.helper_command("demo/apps/canvas_buttons.py", "a.log") == [
        r"C:\Apps\ORION\ORION.exe", "--run-helper", "demo/apps/canvas_buttons.py", "a.log"]


def test_selftest_reports_each_check_and_fails_on_a_required_one(tmp_path, monkeypatch):
    from orion.app import selftest

    def broken(ws):
        raise RuntimeError("Executable doesn't exist")
    monkeypatch.setattr(selftest, "CHECKS", [("files_plan_verify", selftest.check_files, True),
                                             ("safety_layer", selftest.check_safety, True),
                                             ("browser", broken, True)])
    out = tmp_path / "st.json"
    assert selftest.run_selftest(out) == 1
    r = json.loads(out.read_text())
    assert r["checks"]["files_plan_verify"]["ok"] and r["checks"]["safety_layer"]["ok"]
    assert not r["checks"]["browser"]["ok"] and "--install-browser" in r["checks"]["browser"]["detail"]
