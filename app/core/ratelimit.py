"""Global download speed limiter (F1.8): a thread-safe token bucket shared by
every worker connection, so the cap applies to the whole app, not per stream.
"""

from __future__ import annotations

import threading
import time

UNLIMITED = 0


class RateLimiter:
    """Token bucket in bytes/second. A rate of 0 means unlimited.

    Workers call :meth:`throttle` with the size of the chunk they just moved;
    the call sleeps exactly long enough to keep the long-run average at the
    configured rate. The bucket holds at most one second of burst.
    """

    def __init__(self, rate: int = UNLIMITED) -> None:
        self._lock = threading.Lock()
        self._rate = max(0, rate)
        self._tokens = float(self._rate)
        self._updated = time.monotonic()

    @property
    def rate(self) -> int:
        with self._lock:
            return self._rate

    def set_rate(self, rate: int) -> None:
        with self._lock:
            self._rate = max(0, rate)
            self._tokens = min(self._tokens, float(self._rate))
            self._updated = time.monotonic()

    def throttle(self, amount: int) -> None:
        if amount <= 0:
            return
        with self._lock:
            if self._rate == UNLIMITED:
                return
            now = time.monotonic()
            self._tokens = min(float(self._rate), self._tokens + (now - self._updated) * self._rate)
            self._updated = now
            self._tokens -= amount  # may go negative: that's the debt to sleep off
            wait = -self._tokens / self._rate if self._tokens < 0 else 0.0
        if wait > 0:
            time.sleep(wait)
