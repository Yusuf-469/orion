"""Kill switch (S5 early check) and dry-run guarantees. All tests are mock: simulated actions only."""

import random
import threading
import time

import pytest

from orion.execution import Action, DryRunExecutor, RealExecutor
from orion.memory import TaskStore
from orion.orchestration.cancel import KillSwitch, KillSwitchEngaged
from orion.orchestration.runner import TaskRunner, simulated_action
from orion.orchestration.states import Status

pytestmark = [pytest.mark.safety, pytest.mark.mock]

S5_LIMIT_S = 2.0


@pytest.fixture
def env(tmp_path):
    store = TaskStore(tmp_path / "t.db")
    ks = KillSwitch()
    yield store, ks, TaskRunner(store, ks)
    store.close()


def test_kill_switch_latency_10_trials(env, capsys):
    store, ks, runner = env
    rng = random.Random(0)
    latencies = []
    for trial in range(10):
        actions = [simulated_action(f"s{i}", 1.0) for i in range(10)]
        tid = runner.create(f"trial {trial}", actions, dry_run=False)
        token = ks.new_token()
        th = threading.Thread(target=runner.run, args=(tid, actions, RealExecutor(), token))
        th.start()
        time.sleep(rng.uniform(0.1, 1.5))
        t0 = ks.engage("test")
        th.join(timeout=5)
        stopped = time.monotonic()
        assert not th.is_alive()
        latencies.append(stopped - t0)
        assert store.get_task(tid)["status"] == "cancelled"
        assert all(s <= t0 for s in runner.action_starts), "an action started after the kill switch"
        ks.reset()
    with capsys.disabled():
        print(f"\n[S5 mock] stop latency over 10 trials: max={max(latencies)*1000:.1f} ms, "
              f"mean={sum(latencies)/len(latencies)*1000:.1f} ms")
    assert max(latencies) < S5_LIMIT_S


def test_engaged_switch_refuses_new_tasks():
    ks = KillSwitch()
    ks.engage()
    with pytest.raises(KillSwitchEngaged):
        ks.new_token()
    ks.reset()
    ks.new_token()


def test_cancel_before_start_runs_nothing(env):
    store, ks, runner = env
    actions = [simulated_action("s", 0.01)]
    tid = runner.create("t", actions, dry_run=False)
    token = ks.new_token()
    ks.engage()
    assert runner.run(tid, actions, RealExecutor(), token) == Status.CANCELLED
    assert runner.action_starts == []
    assert [s["status"] for s in store.list_steps(tid)] == ["cancelled"]


def test_dry_run_never_calls_action(env):
    store, ks, runner = env
    calls = []
    actions = [Action(name=f"a{i}", fn=lambda tok, i=i: calls.append(i) or "x") for i in range(5)]
    tid = runner.create("dry", actions, dry_run=True)
    final = runner.run(tid, actions, DryRunExecutor(), ks.new_token())
    assert calls == []
    assert final == Status.SKIPPED
    steps = store.list_steps(tid)
    assert all(s["status"] == "skipped" and s["evidence"].startswith("dry-run") for s in steps)
    assert all(s["started_at"] is None for s in steps)


def test_failing_action_fails_task_and_stops(env):
    store, ks, runner = env

    def boom(tok):
        raise RuntimeError("simulated failure token=abc123")

    actions = [simulated_action("ok", 0.01), Action("bad", boom), simulated_action("never", 0.01)]
    tid = runner.create("t", actions, dry_run=False)
    assert runner.run(tid, actions, RealExecutor(), ks.new_token()) == Status.FAILED
    statuses = [s["status"] for s in store.list_steps(tid)]
    assert statuses == ["succeeded", "failed", "skipped"]
    assert "abc123" not in store.get_task(tid)["error"]


def test_success_evidence_is_labelled_simulated(env):
    store, ks, runner = env
    actions = [simulated_action("s", 0.01)]
    tid = runner.create("t", actions, dry_run=False)
    assert runner.run(tid, actions, RealExecutor(), ks.new_token()) == Status.SUCCEEDED
    assert store.list_steps(tid)[0]["evidence"].startswith("simulated:")
