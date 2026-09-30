"""API v1 routes. Handlers parse and validate HTTP input, then delegate.

No business logic lives here: route -> service -> algorithm/repository.
"""

from __future__ import annotations

import hmac
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query, Request

from songnexus.api.container import Container
from songnexus.core.errors import InvalidRequestError, NotFoundError
from songnexus.core.metrics import metrics
from songnexus.schemas import api
from songnexus.schemas.agent import AgentQuery, AgentResponse
from songnexus.services.game_service import LAUNCH_DAY
from songnexus.services.graph_service import parse_categories

router = APIRouter(prefix="/api/v1")
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
ArtistId = Annotated[str, Path(pattern=UUID)]
CategoriesParam = Annotated[
    str | None,
    Query(description="Comma-separated: performance, production, contribution, sampling, engineering, membership"),
]


def container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def _split(raw: str | None) -> list[str] | None:
    return [part for part in raw.split(",") if part.strip()] if raw else None


# -- search ----------------------------------------------------------------------


@router.get("/search", response_model=api.SearchResponse, tags=["search"])
def search(
    q: Annotated[str, Query(min_length=1, max_length=120)],
    types: Annotated[str | None, Query(description="Comma-separated: artist, track, album")] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
    c: Container = Depends(container),
) -> api.SearchResponse:
    allowed = {"artist", "track", "album"}
    entity_types = frozenset(t for t in (_split(types) or []) if t in allowed) or None
    with metrics.timer("search.query_ms"):
        hits = c.store.current.search.search(q, limit=limit, entity_types=entity_types)
    metrics.counter("search.requests")
    if not hits:
        metrics.counter("search.empty_results")  # product signal: what are we missing?
    return api.SearchResponse(
        query=q,
        results=[
            api.SearchResult(
                entity_type=h.entity_type,
                id=h.entity_id,
                name=h.name,
                subtitle=h.subtitle,
                score=h.score,
                match_type=h.match_type,
                matched_on=h.matched_on,
            )
            for h in hits
        ],
    )


# -- catalog -----------------------------------------------------------------------


@router.get("/artists/{artist_id}", response_model=api.ArtistDetail, tags=["catalog"])
def get_artist(artist_id: ArtistId, c: Container = Depends(container)) -> api.ArtistDetail:
    return c.catalog.artist(artist_id)


@router.get("/artists/{artist_id}/neighbors", response_model=api.GraphPayload, tags=["graph"])
def get_neighbors(
    artist_id: ArtistId,
    categories: CategoriesParam = None,
    limit: Annotated[int, Query(ge=1, le=150)] = 40,
    depth: Annotated[int, Query(ge=1, le=2)] = 1,
    min_strength: Annotated[float, Query(ge=0, le=100)] = 0.0,
    c: Container = Depends(container),
) -> api.GraphPayload:
    metrics.counter(f"graph.expand.depth{depth}")
    return c.graph.neighborhood(artist_id, parse_categories(_split(categories)), limit, depth, min_strength)


@router.get("/tracks/{track_id}", response_model=api.TrackDetail, tags=["catalog"])
def get_track(track_id: Annotated[str, Path(pattern=UUID)], c: Container = Depends(container)) -> api.TrackDetail:
    return c.catalog.track(track_id)


# -- graph ---------------------------------------------------------------------------


@router.get("/graph/path", response_model=api.PathResponse, tags=["graph"])
def get_path(
    source: Annotated[str, Query(pattern=UUID)],
    target: Annotated[str, Query(pattern=UUID)],
    mode: Annotated[api.PathMode, Query()] = "shortest",
    categories: CategoriesParam = None,
    max_depth: Annotated[int, Query(ge=1, le=8)] = 6,
    alternatives: Annotated[int, Query(ge=0, le=5)] = 0,
    c: Container = Depends(container),
) -> api.PathResponse:
    result = c.graph.path(source, target, mode, parse_categories(_split(categories)), max_depth, alternatives)
    metrics.counter(f"graph.path.{'found' if result.found else 'not_found'}")
    return result


@router.get("/graph/edge", response_model=api.EdgeEvidenceResponse, tags=["graph"])
def get_edge(
    a: Annotated[str, Query(pattern=UUID)],
    b: Annotated[str, Query(pattern=UUID)],
    categories: CategoriesParam = None,
    c: Container = Depends(container),
) -> api.EdgeEvidenceResponse:
    return c.graph.edge_evidence(a, b, parse_categories(_split(categories)))


@router.get("/graph/centrality", response_model=api.CentralityResponse, tags=["graph"])
def get_centrality(
    metric: Annotated[api.CentralityMetric, Query()] = "pagerank",
    scope: Annotated[str, Query(pattern="^(hydrated|all)$")] = "hydrated",
    categories: CategoriesParam = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    c: Container = Depends(container),
) -> api.CentralityResponse:
    return c.graph.centrality(metric, parse_categories(_split(categories)), limit, scope)


@router.get("/graph/stats", response_model=api.GraphStats, tags=["graph"])
def get_graph_stats(c: Container = Depends(container)) -> api.GraphStats:
    return c.graph.stats()


# -- provenance -----------------------------------------------------------------------


@router.get("/provenance/edge", response_model=api.EdgeProvenanceResponse, tags=["provenance"])
def get_edge_provenance(
    a: Annotated[str, Query(pattern=UUID)],
    b: Annotated[str, Query(pattern=UUID)],
    c: Container = Depends(container),
) -> api.EdgeProvenanceResponse:
    return c.catalog.edge_provenance(a, b)


@router.get("/provenance/{entity_type}/{entity_id}", response_model=api.EntityProvenanceResponse, tags=["provenance"])
def get_entity_provenance(
    entity_type: Annotated[api.EntityType, Path()],
    entity_id: Annotated[str, Path(pattern=UUID)],
    c: Container = Depends(container),
) -> api.EntityProvenanceResponse:
    return c.catalog.entity_provenance(entity_type, entity_id)


# -- agent ------------------------------------------------------------------------------


@router.post("/agent/query", response_model=AgentResponse, tags=["agent"])
def agent_query(body: AgentQuery, request: Request, c: Container = Depends(container)) -> AgentResponse:
    c.agent_rate_limiter.check(request.client.host if request.client else "unknown")
    return c.agent.query(body)


# -- daily game ---------------------------------------------------------------------------


def _puzzle_day(day: date | None) -> date:
    """Default to today (UTC). Allow one day ahead for time zones; never future puzzles beyond that."""
    today = datetime.now(UTC).date()
    chosen = day or today
    if chosen < LAUNCH_DAY or chosen > today + timedelta(days=1):
        raise InvalidRequestError(f"no puzzle for {chosen.isoformat()}", {"first": LAUNCH_DAY.isoformat()})
    return chosen


@router.get("/game/daily", response_model=api.DailyPuzzle, tags=["game"])
def game_daily(
    day: Annotated[date | None, Query(alias="date")] = None, c: Container = Depends(container)
) -> api.DailyPuzzle:
    metrics.counter("game.daily")
    return c.game.daily(_puzzle_day(day))


@router.post("/game/check", response_model=api.GameCheckResponse, tags=["game"])
def game_check(body: api.GameCheckRequest, c: Container = Depends(container)) -> api.GameCheckResponse:
    result = c.game.check(body)
    metrics.counter(f"game.check.{'hit' if result.connected else 'miss'}")
    return result


@router.get("/game/hint", response_model=api.GameHint, tags=["game"])
def game_hint(
    from_id: Annotated[str, Query(pattern=UUID)],
    target_id: Annotated[str, Query(pattern=UUID)],
    c: Container = Depends(container),
) -> api.GameHint:
    metrics.counter("game.hint")
    return c.game.hint(from_id, target_id)


@router.get("/game/solution", response_model=api.PathResponse, tags=["game"])
def game_solution(
    day: Annotated[date | None, Query(alias="date")] = None, c: Container = Depends(container)
) -> api.PathResponse:
    metrics.counter("game.solution")
    return c.game.solution(_puzzle_day(day))


# -- system -------------------------------------------------------------------------------


@router.get("/health", response_model=api.HealthResponse, tags=["system"])
def health(c: Container = Depends(container)) -> api.HealthResponse:
    model = c.store.current
    rows = c.store.count_rows()
    return api.HealthResponse(
        status="ok" if rows.get("artists") else "degraded",
        graph_version=model.version,
        rows=rows,
        llm_available=c.agent.llm_available,
    )


@router.get("/system/metrics", tags=["system"])
def get_metrics(c: Container = Depends(container)) -> dict[str, Any]:
    return {"graph_version": c.store.current.version, **metrics.snapshot()}


@router.post("/system/reload", response_model=api.GraphStats, tags=["system"])
def reload_read_model(
    x_admin_token: Annotated[str, Header()] = "",
    c: Container = Depends(container),
) -> api.GraphStats:
    expected = c.settings.admin_token
    # Disabled unless configured; constant-time comparison when enabled.
    if not expected or not hmac.compare_digest(x_admin_token, expected):
        raise NotFoundError("not found")
    c.store.reload()
    return c.graph.stats()
