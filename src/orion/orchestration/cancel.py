"""Cancellation tokens and the global kill switch.

The kill switch cancels every active token and then *latches*: no new task may
start until a human calls `reset()`. Runners check their token before every
action, and long actions wait on the token instead of sleeping, so a stop takes
effect at the next check (tens of milliseconds for simulated actions).
"""

from __future__ import annotations

import threading
import time


class Cancelled(Exception):
    """Raised inside an action when its token is cancelled."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason: str | None = None
        self.cancelled_at: float | None = None  # time.monotonic()

    def cancel(self, reason: str) -> None:
        if not self._event.is_set():
            self.reason = reason
            self.cancelled_at = time.monotonic()
            self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled(self.reason or "cancelled")

    def wait(self, timeout: float) -> bool:
        """Sleep up to `timeout`s; return True early if cancelled."""
        return self._event.wait(timeout)


class KillSwitchEngaged(RuntimeError):
    pass


class KillSwitch:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: set[CancelToken] = set()
        self._engaged = False
        self.engaged_at: float | None = None

    @property
    def engaged(self) -> bool:
        return self._engaged

    def new_token(self) -> CancelToken:
        """Issue a token for a new task. Refused while the switch is engaged."""
        with self._lock:
            if self._engaged:
                raise KillSwitchEngaged("kill switch engaged; reset it before starting tasks")
            token = CancelToken()
            self._tokens.add(token)
            return token

    def release(self, token: CancelToken) -> None:
        with self._lock:
            self._tokens.discard(token)

    def engage(self, reason: str = "kill switch") -> float:
        with self._lock:
            self._engaged = True
            self.engaged_at = time.monotonic()
            for t in self._tokens:
                t.cancel(reason)
            return self.engaged_at

    def reset(self) -> None:
        with self._lock:
            self._engaged = False
            self.engaged_at = None
