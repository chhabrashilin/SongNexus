"""The agent's allow-listed tools.

Every tool is a thin, read-only adapter over a deterministic service. The
agent cannot run SQL, shell commands, or anything not in ``TOOLS``. Arguments
are validated with Pydantic (unknown fields rejected, ranges bounded) before
execution; invalid calls return an error result the model can correct.

Tool output strings that originate from external data (artist names, titles)
are sanitized and length-limited before they reach the model, and the system
prompt tells the model that tool output is data, never instructions.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from songnexus.agent.ledger import EvidenceLedger
from songnexus.core.errors import SongNexusError
from songnexus.core.metrics import metrics
from songnexus.graph.projection import CATEGORIES, kinds_for
from songnexus.resolution.matcher import Candidate, Decision, resolve
from songnexus.schemas.agent import ToolCallTrace
from songnexus.services.catalog_service import CatalogService
from songnexus.services.graph_service import GraphService, parse_categories

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
Category = Literal["performance", "production", "contribution", "sampling", "engineering", "membership"]
assert set(Category.__args__) == set(CATEGORIES)  # type: ignore[attr-defined]


def clean(text: str | None, limit: int = 200) -> str:
    """Strip control characters and bound length of externally sourced text."""
    return _CONTROL.sub(" ", text or "")[:limit]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchEntitiesArgs(_Args):
    query: str = Field(min_length=1, max_length=120, description="Name as the user wrote it.")
    entity_type: Literal["artist", "track", "album"] = "artist"
    limit: int = Field(default=5, ge=1, le=10)


class ArtistArgs(_Args):
    artist_id: str = Field(pattern=UUID_PATTERN)


class NeighborsArgs(_Args):
    artist_id: str = Field(pattern=UUID_PATTERN)
    categories: list[Category] | None = Field(
        default=None, description="Relationship categories; default excludes engineering."
    )
    limit: int = Field(default=10, ge=1, le=25)


class PathArgs(_Args):
    source_id: str = Field(pattern=UUID_PATTERN)
    target_id: str = Field(pattern=UUID_PATTERN)
    mode: Literal["shortest", "strongest"] = "shortest"
    max_depth: int = Field(default=6, ge=1, le=8)
    alternatives: int = Field(default=0, ge=0, le=3)
    categories: list[Category] | None = None


class EvidenceArgs(_Args):
    artist_a: str = Field(pattern=UUID_PATTERN)
    artist_b: str = Field(pattern=UUID_PATTERN)
    limit: int = Field(default=10, ge=1, le=20)


class RankArgs(_Args):
    metric: Literal["pagerank", "betweenness", "degree"] = "pagerank"
    scope: Literal["seed", "all"] = Field(default="seed", description="'seed' ranks only fully-loaded artists.")
    limit: int = Field(default=10, ge=1, le=20)


@dataclass
class ToolContext:
    graph: GraphService
    catalog: CatalogService
    ledger: EvidenceLedger


@dataclass(frozen=True)
class ToolOutput:
    data: dict[str, Any]
    summary: str


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[_Args]
    handler: Callable[[ToolContext, Any], ToolOutput]

    def definition(self) -> dict[str, Any]:
        """Claude tool definition (JSON Schema generated from the Pydantic model)."""
        return {"name": self.name, "description": self.description, "input_schema": self.args_model.model_json_schema()}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _search_entities(ctx: ToolContext, args: SearchEntitiesArgs) -> ToolOutput:
    hits = ctx.graph.model.search.search(args.query, limit=args.limit, entity_types=frozenset({args.entity_type}))
    candidates = [
        Candidate(
            entity_id=h.entity_id,
            name=h.name,
            aliases=(h.matched_on,) if h.matched_on != h.name else (),
            prior=h.score,
            description=h.subtitle,
        )
        for h in hits
    ]
    resolution = resolve(args.query, candidates)
    if resolution.entity_id and resolution.best:
        ctx.ledger.add_entity(resolution.entity_id, resolution.best.candidate.name, args.entity_type)
    else:
        # Unresolved: the model may list the candidates when asking the user
        # to disambiguate. After a clean match, the other candidates are noise
        # and mentioning them would be unsupported.
        for h in hits:
            ctx.ledger.add_known(h.entity_id, h.name)
    data = {
        "decision": resolution.decision.value,
        "resolved_id": resolution.entity_id,
        "confidence": resolution.confidence,
        "candidates": [
            {"id": h.entity_id, "name": clean(h.name), "description": clean(h.subtitle), "score": h.score} for h in hits
        ],
    }
    if resolution.decision is Decision.MATCHED and resolution.best:
        summary = f"'{args.query}' -> {resolution.best.candidate.name} (confidence {resolution.confidence})"
    else:
        summary = f"'{args.query}' is {resolution.decision.value}; {len(hits)} candidates"
    return ToolOutput(data, summary)


def _get_artist(ctx: ToolContext, args: ArtistArgs) -> ToolOutput:
    detail = ctx.catalog.artist(args.artist_id)
    ctx.ledger.add_entity(detail.id, detail.name)
    data = {
        "id": detail.id,
        "name": clean(detail.name),
        "disambiguation": clean(detail.disambiguation),
        "type": detail.artist_type,
        "country": detail.country,
        "active_from": detail.begin_date,
        "genres": [g.name for g in detail.genres[:8]],
        "connected_artists": detail.degree,
        "connections_by_kind": {c.label: c.artists for c in detail.connections},
        "albums_in_dataset": [f"{clean(a.title)} ({a.year})" for a in detail.albums],
        "fully_loaded": detail.hydrated,
    }
    return ToolOutput(data, f"{detail.name}: {detail.degree} connected artists")


def _get_neighbors(ctx: ToolContext, args: NeighborsArgs) -> ToolOutput:
    categories = parse_categories(args.categories)
    payload = ctx.graph.neighborhood(args.artist_id, categories, limit=args.limit, depth=1, min_strength=0.0)
    graph = ctx.graph.model.graph
    center = graph.nodes[args.artist_id]
    ctx.ledger.add_entity(center.id, center.name)
    neighbors = []
    center_edges = [e for e in payload.edges if args.artist_id in (e.source, e.target)]
    for edge in sorted(center_edges, key=lambda e: (-e.strength, e.source, e.target)):
        other = edge.target if edge.source == args.artist_id else edge.source
        items, total = ctx.graph.evidence_items(graph, args.artist_id, other, kinds_for(categories), limit=2)
        for item in items:
            ctx.ledger.add_evidence(item)
        ctx.ledger.add_entity(other, graph.nodes[other].name)
        neighbors.append(
            {
                "id": other,
                "name": clean(graph.nodes[other].name),
                "strength": edge.strength,
                "kinds": edge.kinds,
                "evidence": [clean(i.sentence, 300) for i in items],
                "evidence_total": total,
            }
        )
    data = {"artist": clean(center.name), "total_connected": payload.total_neighbors, "neighbors": neighbors}
    return ToolOutput(data, f"{len(neighbors)} of {payload.total_neighbors} neighbors of {center.name}")


def _find_path(ctx: ToolContext, args: PathArgs) -> ToolOutput:
    categories = parse_categories(args.categories)
    result = ctx.graph.path(args.source_id, args.target_id, args.mode, categories, args.max_depth, args.alternatives)
    ledger = ctx.ledger
    ledger.path_searched = True
    ledger.add_entity(result.source.id, result.source.name)
    ledger.add_entity(result.target.id, result.target.name)
    if result.path is None:
        ledger.add_limitation(result.explanation)
        return ToolOutput({"found": False, "explanation": clean(result.explanation, 500)}, "no path found")
    ledger.path = result.path
    ledger.path_kinds = kinds_for(categories)
    for node in result.path.nodes:
        ledger.add_entity(node.id, node.name)
    for hop in result.path.hops:
        for item in hop.evidence:
            ledger.add_evidence(item)
    names = {n.id: clean(n.name) for n in result.path.nodes}
    data = {
        "found": True,
        "algorithm": result.algorithm,
        "steps": result.path.length,
        "path": [names[n.id] for n in result.path.nodes],
        "hops": [
            {
                "from": names[h.source],
                "to": names[h.target],
                "strength": h.strength,
                "evidence": [clean(e.sentence, 300) for e in h.evidence],
                "more_evidence": h.evidence_total - len(h.evidence),
            }
            for h in result.path.hops
        ],
        "alternatives": [[clean(n.name) for n in alt.nodes] for alt in result.alternatives],
    }
    for alt in result.alternatives:
        for node in alt.nodes:
            ledger.add_entity(node.id, node.name)
    return ToolOutput(data, f"{result.path.length}-step path via {result.algorithm}")


def _get_connection_evidence(ctx: ToolContext, args: EvidenceArgs) -> ToolOutput:
    response = ctx.graph.edge_evidence(args.artist_a, args.artist_b, parse_categories(None))
    ctx.ledger.add_entity(response.a.id, response.a.name)
    ctx.ledger.add_entity(response.b.id, response.b.name)
    for item in response.evidence[: args.limit]:
        ctx.ledger.add_evidence(item)
    data = {
        "a": clean(response.a.name),
        "b": clean(response.b.name),
        "strength": response.strength,
        "evidence": [clean(e.sentence, 300) for e in response.evidence[: args.limit]],
        "evidence_total": len(response.evidence),
    }
    return ToolOutput(data, f"{len(response.evidence)} pieces of evidence")


def _rank_artists(ctx: ToolContext, args: RankArgs) -> ToolOutput:
    scope = "hydrated" if args.scope == "seed" else "all"
    response = ctx.graph.centrality(args.metric, parse_categories(None), args.limit, scope)
    for entry in response.results:
        ctx.ledger.add_known(entry.id, entry.name)
    data = {
        "metric": response.metric,
        "algorithm": response.algorithm,
        "exact": response.exact,
        "ranking": [
            {"rank": e.rank, "name": clean(e.name), "score": e.score, "genres": e.genres[:3]} for e in response.results
        ],
    }
    return ToolOutput(data, f"top {len(response.results)} by {response.metric}")


def _get_provenance(ctx: ToolContext, args: EvidenceArgs) -> ToolOutput:
    response = ctx.catalog.edge_provenance(args.artist_a, args.artist_b)
    facts = response.facts[: args.limit]
    data = {
        "facts": [
            {
                "fact": clean(f.description, 200),
                "source": f.source,
                "license": f.source_license,
                "source_urls": f.source_urls[:2],
                "retrieved_at": f.retrieved_at,
                "pipeline_version": f.pipeline_version,
                "confidence": f.confidence,
            }
            for f in facts
        ],
        "facts_total": len(response.facts),
    }
    return ToolOutput(data, f"{len(response.facts)} source facts")


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            "search_entities",
            "Resolve a name the user mentioned to a canonical entity ID. Returns a decision: 'matched' "
            "(safe to use resolved_id), 'ambiguous' (ask or explain which one), or 'no_match'. Always call this "
            "before using an ID; never invent IDs.",
            SearchEntitiesArgs,
            _search_entities,
        ),
        Tool(
            "get_artist",
            "Facts about one artist: genres, dataset albums, and how many artists they connect to.",
            ArtistArgs,
            _get_artist,
        ),
        Tool(
            "get_neighbors",
            "An artist's strongest direct connections, each with fact-backed evidence sentences.",
            NeighborsArgs,
            _get_neighbors,
        ),
        Tool(
            "find_path",
            "Compute how two artists are connected. mode='shortest' (fewest steps, bidirectional BFS) or "
            "'strongest' (strongest links, Dijkstra). Returns hops with evidence, or found=false.",
            PathArgs,
            _find_path,
        ),
        Tool(
            "get_connection_evidence",
            "All evidence that two directly connected artists share (tracks, albums, memberships).",
            EvidenceArgs,
            _get_connection_evidence,
        ),
        Tool(
            "rank_artists",
            "Rank artists by graph centrality: 'pagerank' (overall influence in the network), 'betweenness' "
            "(bridges between otherwise separate groups), or 'degree' (number of connections).",
            RankArgs,
            _rank_artists,
        ),
        Tool(
            "get_provenance",
            "Source records (MusicBrainz URLs, retrieval time, pipeline version, confidence) behind the "
            "connection between two directly connected artists.",
            EvidenceArgs,
            _get_provenance,
        ),
    ]
}


def run_tool(ctx: ToolContext, name: str, raw_args: dict[str, Any], step: int) -> tuple[bool, dict[str, Any]]:
    """Validate and execute one tool call; always records a trace."""
    started = time.perf_counter()
    tool = TOOLS.get(name)
    ok = False
    result: dict[str, Any]
    summary: str
    if tool is None:
        result = {"error": f"unknown tool {name!r}; allowed: {sorted(TOOLS)}"}
        summary = "rejected: unknown tool"
    else:
        try:
            args = tool.args_model.model_validate(raw_args)
            output = tool.handler(ctx, args)
            result, summary, ok = output.data, output.summary, True
        except ValidationError as exc:
            errors = [{"field": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()]
            result = {"error": "invalid arguments", "details": errors}
            summary = "rejected: invalid arguments"
        except SongNexusError as exc:
            result = {"error": exc.message, "details": exc.details}
            summary = f"error: {exc.message}"
    latency = round((time.perf_counter() - started) * 1000, 2)
    metrics.observe(f"agent.tool.{name}.ms", latency)
    metrics.counter(f"agent.tool.{name}.{'ok' if ok else 'error'}")
    ctx.ledger.traces.append(
        ToolCallTrace(step=step, tool=name, arguments=raw_args, ok=ok, summary=summary, latency_ms=latency)
    )
    return ok, result
