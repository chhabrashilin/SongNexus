"""Search evaluation: MRR, Hit@1, Recall@k, nDCG@k, and latency.

Compares the production ranker against an exact-match baseline so the value
of normalization, alias, prefix and fuzzy matching is measured, not asserted.
The same harness will compare lexical vs. hybrid retrieval in Phase 4.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from songnexus.db import models as m
from songnexus.db.session import get_engine, session_scope
from songnexus.readmodel import build_read_model
from songnexus.search.index import SearchIndex

Ranker = Callable[[str, int], list[tuple[str, str]]]  # -> [(entity_type, entity_id)]


def resolve_labels(engine: Engine, cases: list[dict[str, Any]]) -> dict[int, set[tuple[str, str]]]:
    """Map each case's (type, mbid) labels to canonical (type, id) pairs."""
    with session_scope(engine) as session:
        mapping = {
            (row.entity_type, row.source_entity_id): row.entity_id
            for row in session.execute(
                select(
                    m.EntitySourceMapping.entity_type,
                    m.EntitySourceMapping.source_entity_id,
                    m.EntitySourceMapping.entity_id,
                )
            )
        }
    labels: dict[int, set[tuple[str, str]]] = {}
    for i, case in enumerate(cases):
        resolved = set()
        for label in case["relevant"]:
            entity_id = mapping.get((label["type"], label["mbid"]))
            if entity_id is None:
                raise ValueError(f"label not in database: {label} (query {case['query']!r})")
            resolved.add((label["type"], entity_id))
        labels[i] = resolved
    return labels


def ndcg_at_k(ranked: list[tuple[str, str]], relevant: set[tuple[str, str]], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, r in enumerate(ranked[:k]) if r in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def evaluate(
    ranker: Ranker, cases: list[dict[str, Any]], labels: dict[int, set[tuple[str, str]]], k: int
) -> dict[str, Any]:
    per_case = []
    latencies = []
    for i, case in enumerate(cases):
        started = time.perf_counter()
        ranked = ranker(case["query"], max(k, 10))
        latencies.append((time.perf_counter() - started) * 1000)
        relevant = labels[i]
        rank = next((pos + 1 for pos, r in enumerate(ranked) if r in relevant), None)
        per_case.append(
            {
                "query": case["query"],
                "category": case["category"],
                "rank": rank,
                "reciprocal_rank": 1.0 / rank if rank else 0.0,
                "hit_at_1": rank == 1,
                "recall_at_k": len(relevant & set(ranked[:k])) / len(relevant),
                "ndcg_at_k": ndcg_at_k(ranked, relevant, k),
            }
        )

    def summarize(rows: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "n": len(rows),
            "mrr": round(statistics.mean(r["reciprocal_rank"] for r in rows), 4),
            "hit_at_1": round(statistics.mean(1.0 if r["hit_at_1"] else 0.0 for r in rows), 4),
            f"recall_at_{k}": round(statistics.mean(r["recall_at_k"] for r in rows), 4),
            f"ndcg_at_{k}": round(statistics.mean(r["ndcg_at_k"] for r in rows), 4),
        }

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_case:
        by_category[row["category"]].append(row)
    ordered_latency = sorted(latencies)
    return {
        "overall": summarize(per_case),
        "by_category": {c: summarize(rows) for c, rows in sorted(by_category.items())},
        "latency_ms": {
            "p50": round(ordered_latency[len(ordered_latency) // 2], 2),
            "p95": round(ordered_latency[min(len(ordered_latency) - 1, int(0.95 * len(ordered_latency)))], 2),
        },
        "misses": [r for r in per_case if not r["hit_at_1"]],
    }


def production_ranker(index: SearchIndex) -> Ranker:
    return lambda q, limit: [(h.entity_type, h.entity_id) for h in index.search(q, limit=limit)]


def exact_baseline_ranker(index: SearchIndex) -> Ranker:
    """Normalized exact match on names/aliases only, no ranking signals."""
    return lambda q, limit: [(d.entity_type, d.entity_id) for d in index.exact(q)][:limit]


def run_search_eval(cases_path: Path, k: int = 5, engine: Engine | None = None) -> dict[str, Any]:
    engine = engine or get_engine()
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    labels = resolve_labels(engine, cases)
    model = build_read_model(engine)
    return {
        "graph_version": model.version,
        "cases": len(cases),
        "k": k,
        "systems": {
            "exact_baseline": evaluate(exact_baseline_ranker(model.search), cases, labels, k),
            "lexical_ranker": evaluate(production_ranker(model.search), cases, labels, k),
        },
    }
