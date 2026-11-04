"""GPU energy used by a piece of work, read from the NVIDIA driver's own energy counter.

Method from OpenJarvis (Stanford, Apache-2.0; telemetry/energy_nvidia.py), whose research measures
"intelligence per watt": read the cumulative counter (millijoules, Volta and newer) before and after,
and report the difference. It counts everything the GPU did in that time, including other programs,
so trials should run with the PC otherwise idle. Without an NVIDIA GPU or `nvidia-ml-py`, joules is None.
"""

from __future__ import annotations

import time


def _counter_mj() -> int | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        return int(pynvml.nvmlDeviceGetTotalEnergyConsumption(pynvml.nvmlDeviceGetHandleByIndex(0)))
    except Exception:  # noqa: BLE001 - no GPU, no driver, no library: energy is simply unknown
        return None


class GpuEnergy:
    """`with GpuEnergy() as e: ...` then e.joules (None if unknown) and e.seconds."""

    def __enter__(self) -> "GpuEnergy":
        self._start, self._t0 = _counter_mj(), time.monotonic()
        self.joules: float | None = None
        self.seconds = 0.0
        return self

    def __exit__(self, *exc) -> None:
        end = _counter_mj()
        self.seconds = time.monotonic() - self._t0
        if self._start is not None and end is not None and end >= self._start:
            self.joules = (end - self._start) / 1000.0

    @property
    def watts(self) -> float | None:
        return self.joules / self.seconds if self.joules is not None and self.seconds > 0 else None
