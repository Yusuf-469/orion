"""Interface backend without a window (mock: no model, no browser, no audio)."""

import threading
import time

import pytest

from orion.config import OrionConfig
from orion.orchestration.cancel import CancelToken
from orion.policy.engine import ConfirmationRequest
from orion.tools.base import SideEffect


@pytest.fixture
def backend(tmp_path):
    from orion.ui.backend import Backend
    b = Backend(OrionConfig(data_dir=tmp_path / "data", workspace_dir=tmp_path / "ws"))
    b.settings["voice"] = False
    b.events = []
    b.emit = b.events.append
    return b


@pytest.mark.parametrize("goal,first", [
    ("Find jobs that match my CV at https://example.com/careers", "jobs.shortlist"),
    ("Compare the Pixel 9 and iPhone 16", "research.compare"),
    ("Work out 15% of 2400 in Calculator", "calculator.compute"),
    ("Fill in the survey form at https://example.com/form", "web.search"),
])
def test_tools_are_routed_by_goal(goal, first):
    from orion.ui.backend import choose_tools
    assert choose_tools(goal)[0] == first


def test_settings_and_profile_are_saved(backend, tmp_path):
    backend.set_setting("voice_id", "kokoro:bm_george")
    backend.set_setting("voice_rate", 1.2)
    backend.set_setting("not_a_setting", 1)
    backend.save_profile("  Asha Rao ", "Email: asha@example.com")
    from orion.ui.backend import Backend
    again = Backend(OrionConfig(data_dir=tmp_path / "data", workspace_dir=tmp_path / "ws"))
    assert again.settings["voice_id"] == "kokoro:bm_george" and again.settings["voice_rate"] == 1.2
    assert "not_a_setting" not in again.settings
    assert again.get_state()["profile"] == {"name": "Asha Rao", "facts": "Email: asha@example.com"}


def _answer_when_asked(backend, value):
    before = len([e for e in backend.events if e["kind"] in ("confirm", "ask", "choose")])

    def go():
        for _ in range(200):
            ev = [e for e in backend.events if e["kind"] in ("confirm", "ask", "choose")]
            if len(ev) > before:   # a NEW dialog, not one answered earlier
                backend.answer(ev[-1]["id"], value)
                return
            time.sleep(0.02)
    threading.Thread(target=go, daemon=True).start()


def test_confirmation_round_trip(backend):
    req = ConfirmationRequest("web.submit", SideEffect.CONSEQUENTIAL, "Press 'Submit'?", "What is filled in:\nName: A")
    _answer_when_asked(backend, True)
    assert backend.confirm(req, CancelToken()) is True
    _answer_when_asked(backend, False)
    assert backend.confirm(req, CancelToken()) is False


def test_question_round_trip_and_blank_answer_is_none(backend):
    _answer_when_asked(backend, "blue")
    assert backend.ask("Which colour?", CancelToken()) == "blue"
    _answer_when_asked(backend, "   ")
    assert backend.ask("Which colour?", CancelToken()) is None


def test_kill_switch_closes_an_open_dialog_and_answers_no(backend):
    t = CancelToken()
    threading.Timer(0.2, lambda: t.cancel("STOP")).start()
    req = ConfirmationRequest("web.submit", SideEffect.CONSEQUENTIAL, "Press?", "x")
    assert backend.confirm(req, t) is False
    assert any(e["kind"] == "dialog_closed" for e in backend.events)


def test_a_second_goal_is_refused_while_one_runs(backend):
    backend.busy.acquire()
    try:
        assert backend.run("list files") == ""
        assert any(e["kind"] == "error" and "already working" in e["message"] for e in backend.events)
    finally:
        backend.busy.release()
