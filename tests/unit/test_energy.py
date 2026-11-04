"""GPU energy reading: difference of the driver's counter; unknown when there is no counter."""

import orion.observability.energy as energy


def test_joules_are_the_counter_difference(monkeypatch):
    readings = iter([1_000_000, 1_250_000])   # millijoules
    monkeypatch.setattr(energy, "_counter_mj", lambda: next(readings))
    with energy.GpuEnergy() as e:
        pass
    assert e.joules == 250.0 and e.seconds >= 0


def test_unknown_without_a_counter(monkeypatch):
    monkeypatch.setattr(energy, "_counter_mj", lambda: None)
    with energy.GpuEnergy() as e:
        pass
    assert e.joules is None and e.watts is None
