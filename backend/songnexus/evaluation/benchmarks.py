"""Path-algorithm benchmarks on the loaded graph.

Measures, over the same seeded random artist pairs:

* unidirectional BFS vs bidirectional BFS vs Dijkstra: latency and nodes expanded
* correctness cross-check: BFS and bidirectional BFS must agree on length
* cold vs cached latency of the full path use case (GraphService.path)

Numbers depend on hardware; the output records the environment. Nothing here
is copied into documentation without a recorded run.
"""

from __future__ import annotations

import platform
import random
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

from sqlalchemy import Engine

from songnexus.core.config import get_settings
from songnexus.db.session import get_engine
from songnexus.graph import algorithms as alg
from songnexus.graph.projection import DEFAULT_CATEGORIES, kinds_for
from songnexus.readmodel import ReadModelStore
from songnexus.services.graph_service import GraphService


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": round(statistics.mean(ordered), 4),
        "p50": round(ordered[len(ordered) // 2], 4),
        "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4),
        "max": round(ordered[-1], 4),
    }


def _time(fn: Callable[[], alg.PathResult]) -> tuple[alg.PathResult, float]:
    started = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - started) * 1000


def run_path_benchmarks(pairs: int = 300, seed: int = 7, engine: Engine | None = None) -> dict[str, Any]:
    settings = get_settings()
    store = ReadModelStore(engine or get_engine())
    model = store.current
    service = GraphService(store, settings)
    kinds = kinds_for(DEFAULT_CATEGORIES)
    adj = model.graph.adjacency(kinds)
    component = sorted(alg.connected_components(adj)[0])
    rng = random.Random(seed)
    sample = [tuple(rng.sample(component, 2)) for _ in range(pairs)]

    timings: dict[str, list[float]] = {"bfs": [], "bidirectional_bfs": [], "dijkstra": []}
    expanded: dict[str, list[float]] = {"bfs": [], "bidirectional_bfs": [], "dijkstra": []}
    lengths: list[float] = []
    disagreements = 0
    for s, t in sample:
        bfs, ms = _time(partial(alg.bfs_path, adj, s, t))
        timings["bfs"].append(ms)
        expanded["bfs"].append(bfs.expanded)
        bi, ms = _time(partial(alg.bidirectional_bfs_path, adj, s, t))
        timings["bidirectional_bfs"].append(ms)
        expanded["bidirectional_bfs"].append(bi.expanded)
        dj, ms = _time(partial(alg.dijkstra_path, adj, s, t))
        timings["dijkstra"].append(ms)
        expanded["dijkstra"].append(dj.expanded)
        assert bfs.path is not None and bi.path is not None
        lengths.append(len(bfs.path) - 1)
        disagreements += len(bfs.path) != len(bi.path)

    cold: list[float] = []
    warm: list[float] = []
    for s, t in sample[:50]:
        for bucket in (cold, warm):  # second call hits the read-model path cache
            started = time.perf_counter()
            service.path(s, t, "shortest", DEFAULT_CATEGORIES, max_depth=8, alternatives=0)
            bucket.append((time.perf_counter() - started) * 1000)

    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "graph_version": model.version,
        "graph": {
            "nodes": len(adj),
            "edges": sum(len(v) for v in adj.values()) // 2,
            "largest_component": len(component),
        },
        "pairs": pairs,
        "seed": seed,
        "path_length": _summary(lengths),
        "latency_ms": {name: _summary(v) for name, v in timings.items()},
        "nodes_expanded": {name: _summary(v) for name, v in expanded.items()},
        "bfs_vs_bidirectional_length_disagreements": disagreements,
        "path_use_case_ms": {"cold": _summary(cold), "cached": _summary(warm)},
    }
