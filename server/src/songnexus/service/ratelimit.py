"""Per-client token-bucket rate limits, by method class.

Buckets live in instance memory and are never logged or persisted. Cloud Run
runs several instances, so the effective limit is per instance; that is
acceptable as abuse protection at demo scale (plan §19) and documented as such.
"""

from __future__ import annotations

import enum
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from songnexus.service.errors import ApiError, Status

MAX_TRACKED_CLIENTS = 10_000


class MethodClass(enum.StrEnum):
    """Groups of methods that share a budget."""

    READ = "read"  # catalog reads and search
    ANALYZE = "analyze"  # path finding, comparison, playlist analysis
    WRITE = "write"  # user data changes


DEFAULT_LIMITS_PER_MINUTE = {
    MethodClass.READ: 600,
    MethodClass.ANALYZE: 120,
    MethodClass.WRITE: 60,
}


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """Token buckets keyed by (client, method class)."""

    def __init__(
        self,
        limits_per_minute: dict[MethodClass, int] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Creates a limiter.

        Args:
            limits_per_minute: Sustained requests per minute per class; the
                bucket capacity (burst) equals the per-minute limit.
            clock: Monotonic clock in seconds (injected by tests).
        """
        self._limits = {**DEFAULT_LIMITS_PER_MINUTE, **(limits_per_minute or {})}
        self._buckets: dict[tuple[str, MethodClass], _Bucket] = {}
        self._lock = threading.Lock()
        self._now = clock

    def check(self, client: str, method_class: MethodClass) -> None:
        """Consumes one token, or raises RESOURCE_EXHAUSTED with ``Retry-After``.

        Raises:
            ApiError: The client is over its limit for this class.
        """
        capacity = float(max(1, self._limits[method_class]))
        refill_per_s = capacity / 60.0
        now = self._now()
        key = (client, method_class)
        with self._lock:
            if len(self._buckets) > MAX_TRACKED_CLIENTS:
                self._buckets.clear()  # Bounded memory; worst case is a brief reset.
            bucket = self._buckets.get(key) or _Bucket(capacity, now)
            bucket.tokens = min(capacity, bucket.tokens + (now - bucket.updated) * refill_per_s)
            bucket.updated = now
            self._buckets[key] = bucket
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return
            retry_after = math.ceil((1.0 - bucket.tokens) / refill_per_s)
        raise ApiError(
            Status.RESOURCE_EXHAUSTED,
            "Too many requests; retry later.",
            reason="RATE_LIMITED",
            metadata={"methodClass": method_class.value, "retryAfterSeconds": str(retry_after)},
            headers={"Retry-After": str(retry_after)},
        )
