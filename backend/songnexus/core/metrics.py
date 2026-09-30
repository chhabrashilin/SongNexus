"""Minimal in-process metrics: counters and latency summaries.

This is intentionally small: it answers "what is p95 latency of the path
endpoint right now?" without new infrastructure. The interface (``counter`` /
``observe`` / ``timer``) maps one-to-one onto OpenTelemetry instruments, so the
registry can be swapped for an OTel exporter without touching call sites.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

_RESERVOIR_SIZE = 1024


@dataclass
class _Summary:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0
    reservoir: list[float] = field(default_factory=list)

    def add(self, value: float, rng: random.Random) -> None:
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)
        # Vitter's Algorithm R: a uniform sample of all observations so far.
        if len(self.reservoir) < _RESERVOIR_SIZE:
            self.reservoir.append(value)
        else:
            slot = rng.randrange(self.count)
            if slot < _RESERVOIR_SIZE:
                self.reservoir[slot] = value

    def snapshot(self) -> dict[str, float]:
        ordered = sorted(self.reservoir)
        return {
            "count": self.count,
            "mean": self.total / self.count if self.count else 0.0,
            "p50": _quantile(ordered, 0.50),
            "p95": _quantile(ordered, 0.95),
            "p99": _quantile(ordered, 0.99),
            "max": self.maximum,
        }


def _quantile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._summaries: dict[str, _Summary] = {}
        self._rng = random.Random(0)

    def counter(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._summaries.setdefault(name, _Summary()).add(value, self._rng)

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, (time.perf_counter() - start) * 1000.0)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": dict(sorted(self._counters.items())),
                "latency_ms": {k: v.snapshot() for k, v in sorted(self._summaries.items())},
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._summaries.clear()


metrics = MetricsRegistry()
