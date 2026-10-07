"""Analysis methods: FindPath (six degrees) and CompareArtists."""

from __future__ import annotations

import itertools
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from songnexus.core.graph import algorithms as alg
from songnexus.core.graph.compare import compare
from songnexus.core.graph.explain import explain_path
from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
    node_filter,
    parse_name,
    rate_limited,
    read_model,
    require_artist,
    viewer,
)
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.catalog import Categories, Genres, kinds_from
from songnexus.service.routes.common import (
    MAX_ALTERNATIVES,
    MAX_PATH_STEPS,
    db_session,
    set_cache_control,
)
from songnexus.storage import catalog_repository as repo

router = APIRouter(
    prefix="/v1", tags=["analysis"], dependencies=[Depends(rate_limited(MethodClass.ANALYZE))]
)

ReadModelDep = Annotated[ReadModel, Depends(read_model)]
ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
EVIDENCE_PER_STEP = 3


def _endpoints(graph: ArtistGraph, *names: tuple[str, str]) -> list[str]:
    """Parses and checks the artists a method starts from.

    Endpoints are the viewer's explicit choice, so they are allowed even when
    blocked; blocks apply to everything in between (US-17).
    """
    ids = []
    for value, field in names:
        artist_id = parse_name(value, "artists", field=field)
        require_artist(graph, artist_id)
        ids.append(artist_id)
    return ids


@router.get(
    "/artists/{artist:rid}:findPath", response_model=api.FindPathResponse, summary="FindPath"
)
def find_path(
    artist: str,
    model: ReadModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    target: Annotated[str, Query(description="Resource name of the artist to reach.")],
    mode: api.PathMode = api.PathMode.FEWEST_STEPS,
    max_steps: Annotated[int, Query(alias="maxSteps", ge=1, le=MAX_PATH_STEPS)] = MAX_PATH_STEPS,
    alternatives: Annotated[int, Query(ge=0, le=MAX_ALTERNATIVES)] = 0,
    categories: Categories = [],  # noqa: B006 - FastAPI copies query defaults
    genres: Genres = [],  # noqa: B006
    include_unknown_genre: Annotated[bool, Query(alias="includeUnknownGenre")] = True,
) -> api.FindPathResponse:
    """Finds how two artists connect, with evidence for every step.

    Filters (genres, blocks) apply to every intermediate artist. The endpoints
    are the viewer's choice and are not genre-filtered. "Not connected within
    the limit" means not connected in our data (yet), never "not connected".
    """
    graph = model.graph
    source, goal = _endpoints(graph, (artist, "name"), (target, "target"))
    kinds = kinds_from(categories)
    flt: NodeFilter = node_filter(
        who, genres, include_unknown_genre=include_unknown_genre, graph=graph
    )
    allowed = flt.predicate(graph)
    adjacency = graph.adjacency(kinds)

    if mode is api.PathMode.STRONGEST_LINKS:
        result = alg.dijkstra_path(adjacency, source, goal, max_depth=max_steps, allowed=allowed)
    else:
        result = alg.bidirectional_bfs_path(
            adjacency, source, goal, max_depth=max_steps, allowed=allowed
        )
    set_cache_control(response, who)
    if result.path is None:
        outcome = (
            api.PathOutcome.SEARCH_LIMIT_REACHED
            if result.truncated
            else api.PathOutcome.NOT_CONNECTED_WITHIN_LIMIT
        )
        return api.FindPathResponse(outcome=outcome, steps=[], graph_version=model.version)

    steps = explain_path(graph, result.path, kinds, per_step=EVIDENCE_PER_STEP)
    sources = repo.subject_sources(session, convert.subject_keys(e for step in steps for e in step))
    other_routes: list[list[api.ArtistSummary]] = []
    if alternatives and mode is api.PathMode.FEWEST_STEPS:
        for route in alg.yen_k_shortest_paths(
            adjacency, source, goal, alternatives + 1, max_depth=max_steps, allowed=allowed
        ):
            if route != result.path and len(other_routes) < alternatives:
                other_routes.append([convert.artist_summary(graph, a) for a in route])
    return api.FindPathResponse(
        outcome=api.PathOutcome.FOUND,
        steps=[
            api.PathStep(
                from_artist=convert.artist_summary(graph, u),
                to_artist=convert.artist_summary(graph, v),
                strength=round(adjacency[u][v], 4),
                evidence=[convert.evidence(e, sources) for e in explanations],
            )
            for (u, v), explanations in zip(itertools.pairwise(result.path), steps, strict=True)
        ],
        alternatives=other_routes,
        graph_version=model.version,
    )


@router.get(
    "/artists/{artist:rid}:compare",
    response_model=api.CompareArtistsResponse,
    summary="CompareArtists",
)
def compare_artists(
    artist: str,
    model: ReadModelDep,
    who: ViewerDep,
    response: Response,
    other: Annotated[str, Query(description="Resource name of the artist to compare with.")],
    categories: Categories = [],  # noqa: B006
) -> api.CompareArtistsResponse:
    """Compares two artists: shared genres, mutual collaborators and the path between."""
    graph = model.graph
    a, b = _endpoints(graph, (artist, "name"), (other, "other"))
    kinds = kinds_from(categories)
    flt = node_filter(who, [], include_unknown_genre=True, graph=graph)
    result = compare(graph, a, b, kinds, node_filter=flt, max_depth=MAX_PATH_STEPS)
    set_cache_control(response, who)
    return api.CompareArtistsResponse(
        artist_a=convert.artist_summary(graph, a),
        artist_b=convert.artist_summary(graph, b),
        genre_overlap=None if result.genre_overlap is None else round(result.genre_overlap, 4),
        shared_genres=[
            api.SharedGenre(
                genre=f"genres/{g.genre_id}",
                display_name=g.name,
                share_a=round(g.share_a, 4),
                share_b=round(g.share_b, 4),
            )
            for g in result.shared_genres
        ],
        mutual_collaborators=[
            convert.artist_summary(graph, n) for n in result.mutual_collaborators
        ],
        directly_connected=result.directly_connected,
        path=[convert.artist_summary(graph, n) for n in result.path.path or ()],
        counts_a={api.CollaborationType(t.value): n for t, n in result.counts_a.items()},
        counts_b={api.CollaborationType(t.value): n for t, n in result.counts_b.items()},
        graph_version=model.version,
    )
