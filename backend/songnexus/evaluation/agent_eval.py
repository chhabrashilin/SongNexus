"""Agent evaluation harness.

Metrics (definitions in docs/evaluation.md):

* tool_selection_accuracy - expected tools are a subset of the tools used
* task_success_rate       - every observable expectation of the case holds
* grounded_rate           - answer passed the grounding verifier
* unsupported_claim_rate  - answer mentioned artists no tool returned
* limitation_admission    - on cases that require it, a limitation was stated
* latency p50/p95

Deterministic mode is free and reproducible and runs in CI. LLM mode needs
ANTHROPIC_API_KEY, costs money per run, and is run deliberately.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from songnexus.agent.llm import make_claude_client
from songnexus.agent.service import AgentService
from songnexus.core.config import get_settings
from songnexus.core.ids import artist_id_for_mbid
from songnexus.db.session import get_engine
from songnexus.readmodel import ReadModelStore
from songnexus.schemas.agent import AgentQuery, AgentResponse
from songnexus.services.catalog_service import CatalogService
from songnexus.services.graph_service import GraphService


def check_case(case: dict[str, Any], response: AgentResponse) -> dict[str, Any]:
    expect = case["expect"]
    used = {t.tool for t in response.tools_used if t.ok}
    failures: list[str] = []

    if "path_found" in expect and (response.path is not None) != expect["path_found"]:
        failures.append(f"path_found={response.path is not None}, expected {expect['path_found']}")
    if response.path is not None and "max_path_length" in expect and response.path.length > expect["max_path_length"]:
        failures.append(f"path length {response.path.length} > {expect['max_path_length']}")
    entity_ids = {e.id for e in response.entities}
    for mbid in expect.get("entities_include", []):
        if artist_id_for_mbid(mbid) not in entity_ids:
            failures.append(f"missing entity {mbid}")
    if len(response.evidence) < expect.get("min_evidence", 0):
        failures.append(f"only {len(response.evidence)} evidence items")
    if expect.get("admits_limitation") and not response.limitations:
        failures.append("no limitation stated")

    tools_ok = set(case["expected_tools"]) <= used
    if not tools_ok:
        failures.append(f"tools used {sorted(used)}, expected {case['expected_tools']}")
    return {
        "id": case["id"],
        "category": case["category"],
        "tools_ok": tools_ok,
        "success": not failures,
        "failures": failures,
        "grounded": response.grounding.verified,
        "unsupported_mentions": response.grounding.unsupported_mentions,
        "limitation_expected": bool(expect.get("admits_limitation")),
        "limitation_stated": bool(response.limitations),
        "mode_used": response.mode_used,
        "latency_ms": response.elapsed_ms,
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    return round(statistics.mean(1.0 if r[key] else 0.0 for r in rows), 4) if rows else 0.0


def run_agent_eval(cases_path: Path, mode: str = "deterministic", engine: Engine | None = None) -> dict[str, Any]:
    settings = get_settings()
    engine = engine or get_engine()
    store = ReadModelStore(engine)
    graph = GraphService(store, settings)
    catalog = CatalogService(engine, store)
    client = make_claude_client() if mode == "llm" else None
    if mode == "llm" and client is None:
        raise RuntimeError("LLM mode requires ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN)")
    agent = AgentService(graph, catalog, settings, client)

    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        response = agent.query(AgentQuery(question=case["question"], mode=mode))
        rows.append(check_case(case, response))

    limitation_rows = [r for r in rows if r["limitation_expected"]]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    latencies = sorted(r["latency_ms"] for r in rows)
    return {
        "mode": mode,
        "graph_version": store.current.version,
        "cases": len(rows),
        "metrics": {
            "tool_selection_accuracy": _rate(rows, "tools_ok"),
            "task_success_rate": _rate(rows, "success"),
            "grounded_rate": _rate(rows, "grounded"),
            "unsupported_claim_rate": round(
                statistics.mean(1.0 if r["unsupported_mentions"] else 0.0 for r in rows), 4
            ),
            "limitation_admission": _rate(limitation_rows, "limitation_stated"),
            "llm_fallbacks": sum(1 for r in rows if r["mode_used"] != mode),
            "latency_ms_p50": latencies[len(latencies) // 2],
            "latency_ms_p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
        },
        "by_category": {
            c: {"n": len(v), "task_success_rate": _rate(v, "success")} for c, v in sorted(by_category.items())
        },
        "failures": [{"id": r["id"], "failures": r["failures"]} for r in rows if not r["success"]],
    }
