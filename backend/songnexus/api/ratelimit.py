"""In-process token-bucket rate limiter.

Protects the agent endpoint (each call may cost an LLM request). Buckets are
keyed by client address, held only in memory and never logged or persisted.
A multi-instance deployment would move this to Redis (docs/security.md).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from songnexus.core.errors import RateLimitedError

MAX_TRACKED_CLIENTS = 10_000


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = float(max(1, per_minute))
        self._refill_per_s = self._capacity / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._now = clock

    def check(self, key: str) -> None:
        now = self._now()
        with self._lock:
            if len(self._buckets) > MAX_TRACKED_CLIENTS:
                self._buckets.clear()  # bounded memory; worst case: a brief reset
            bucket = self._buckets.get(key) or _Bucket(self._capacity, now)
            bucket.tokens = min(self._capacity, bucket.tokens + (now - bucket.updated) * self._refill_per_s)
            bucket.updated = now
            if bucket.tokens < 1.0:
                self._buckets[key] = bucket
                retry_after = (1.0 - bucket.tokens) / self._refill_per_s
                raise RateLimitedError("too many requests", {"retry_after_s": round(retry_after, 1)})
            bucket.tokens -= 1.0
            self._buckets[key] = bucket
