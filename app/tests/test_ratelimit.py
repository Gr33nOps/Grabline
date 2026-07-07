from __future__ import annotations

import time

from app.core.ratelimit import RateLimiter


def test_unlimited_never_sleeps():
    limiter = RateLimiter(0)
    started = time.monotonic()
    for _ in range(1000):
        limiter.throttle(10_000_000)
    assert time.monotonic() - started < 0.5


def test_burst_is_free_then_throttles():
    limiter = RateLimiter(1_000_000)  # 1 MB/s, bucket starts with 1 MB
    started = time.monotonic()
    limiter.throttle(500_000)
    limiter.throttle(500_000)  # exactly the burst: still free
    assert time.monotonic() - started < 0.2
    limiter.throttle(500_000)  # 0.5 s of debt
    elapsed = time.monotonic() - started
    assert 0.4 <= elapsed < 2.0


def test_set_rate_zero_lifts_the_cap():
    limiter = RateLimiter(1000)
    limiter.set_rate(0)
    started = time.monotonic()
    limiter.throttle(10_000_000)
    assert time.monotonic() - started < 0.2


def test_negative_amounts_ignored():
    limiter = RateLimiter(1000)
    limiter.throttle(0)
    limiter.throttle(-5)  # no crash, no sleep
