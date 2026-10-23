import threading

import pytest

from orion.memory import TaskStore
from orion.orchestration.states import TERMINAL, InvalidTransition, Status, check_transition


@pytest.fixture
def store(tmp_path):
    s = TaskStore(tmp_path / "t.db")
    yield s
    s.close()


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_states_are_final(terminal):
    for target in Status:
        with pytest.raises(InvalidTransition):
            check_transition(terminal, target)


def test_cannot_skip_running():
    with pytest.raises(InvalidTransition):
        check_transition(Status.PENDING, Status.SUCCEEDED)


def test_task_lifecycle_persisted(store, tmp_path):
    tid = store.create_task("demo", dry_run=True)
    for s in (Status.READY, Status.RUNNING, Status.SUCCEEDED):
        store.set_task_status(tid, s)
    store.close()
    reopened = TaskStore(tmp_path / "t.db")
    t = reopened.get_task(tid)
    assert t["status"] == "succeeded" and t["dry_run"] == 1
    reopened.close()


def test_invalid_transition_writes_nothing(store):
    tid = store.create_task("demo", dry_run=False)
    with pytest.raises(InvalidTransition):
        store.set_task_status(tid, Status.SUCCEEDED)
    assert store.get_task(tid)["status"] == "pending"


def test_step_timestamps_and_evidence(store):
    tid = store.create_task("demo", dry_run=False)
    sid = store.add_step(tid, 0, "step one")
    store.set_step_status(sid, Status.READY)
    store.set_step_status(sid, Status.RUNNING)
    store.set_step_status(sid, Status.SUCCEEDED, evidence="simulated: slept 0.1s")
    step = store.list_steps(tid)[0]
    assert step["started_at"] is not None and step["ended_at"] >= step["started_at"]
    assert step["evidence"] == "simulated: slept 0.1s"


def test_error_and_event_text_redacted(store):
    tid = store.create_task("demo", dry_run=False)
    store.set_task_status(tid, Status.READY)
    store.set_task_status(tid, Status.RUNNING)
    store.set_task_status(tid, Status.FAILED, error="boom password=hunter2")
    store.add_event(tid, "ERROR", "failure", "token=abc123", {"api_key": "k"})
    assert "hunter2" not in store.get_task(tid)["error"]
    ev = store.list_events(tid)[0]
    assert "abc123" not in ev["message"] and '"k"' not in ev["data"]


def test_concurrent_writers(store):
    tid = store.create_task("demo", dry_run=True)

    def writer(n):
        for i in range(50):
            store.add_event(tid, "INFO", "t", f"{n}-{i}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_events(tid)) == 200
