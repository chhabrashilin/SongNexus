"""Catalog methods: artists, connections, collaborations, recordings, search, genres."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from songnexus.core.graph import collaborations as collab
from songnexus.core.graph.explain import explain_edge
from songnexus.core.graph.model import DEFAULT_CATEGORIES, EdgeKind, kinds_for
from songnexus.core.search import EntityType as CoreEntityType
from songnexus.core.search import MatchType
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
from songnexus.service.errors import invalid_argument, not_found
from songnexus.service.pagination import fingerprint, paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import (
    MAX_QUERY_LENGTH,
    db_session,
    set_cache_control,
)
from songnexus.storage import catalog_repository as repo

router = APIRouter(
    prefix="/v1", tags=["catalog"], dependencies=[Depends(rate_limited(MethodClass.READ))]
)

ReadModelDep = Annotated[ReadModel, Depends(read_model)]
ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
Categories = Annotated[
    list[api.ConnectionCategory],
    Query(
        description="Connection categories to include (default: all except LABELS, ENGINEERING)."
    ),
]
Genres = Annotated[list[str], Query(description="Genre resource names to stay within.")]
PageSize = Annotated[int, Query(alias="pageSize", ge=0, le=1000)]
PageToken = Annotated[str, Query(alias="pageToken", max_length=512)]

HIGHLIGHTS_PER_CONNECTION = 2


def kinds_from(categories: list[api.ConnectionCategory]) -> frozenset[EdgeKind]:
    """Returns the enabled edge kinds for requested categories (defaults when empty)."""
    if not categories:
        return kinds_for(DEFAULT_CATEGORIES)
    return kinds_for(convert.category(c) for c in categories)


@router.get("/artists/{artist:rid}", response_model=api.Artist, summary="GetArtist")
def get_artist(
    artist: str, model: ReadModelDep, session: SessionDep, response: Response
) -> api.Artist:
    """Returns an artist with genres, aliases, links and sources."""
    artist_id = parse_name(artist, "artists", field="name")
    graph = model.graph
    require_artist(graph, artist_id)
    node = graph.nodes[artist_id]
    details = repo.artist_details(session, artist_id)
    set_cache_control(response, None)
    return api.Artist(
        **convert.artist_summary(graph, artist_id).model_dump(),
        begin_date=node.begin_date,
        detail_level=node.detail_level,
        genres=[
            api.GenreShare(
                genre=f"genres/{g.genre_id}", display_name=g.name, share=round(g.share, 4)
            )
            for g in node.genres
        ],
        aliases=[
            api.Alias(display_name=a.name, alias_type=a.alias_type, locale=a.locale)
            for a in details.aliases
        ],
        links=[api.Link(link_type=link.link_type, url=link.url) for link in details.links],
        connection_count=len(graph.adjacency(kinds_for(DEFAULT_CATEGORIES))[artist_id]),
        sources=convert.source_links(details.sources),
        graph_version=model.version,
    )


@router.get(
    "/artists/{artist:rid}/connections",
    response_model=api.ListArtistConnectionsResponse,
    summary="ListArtistConnections",
)
def list_artist_connections(
    artist: str,
    model: ReadModelDep,
    who: ViewerDep,
    response: Response,
    categories: Categories = [],  # noqa: B006 - FastAPI copies query defaults
    genres: Genres = [],  # noqa: B006
    include_unknown_genre: Annotated[bool, Query(alias="includeUnknownGenre")] = True,
    order_by: Annotated[str, Query(alias="orderBy")] = "strength desc",
    page_size: PageSize = 25,
    page_token: PageToken = "",
) -> api.ListArtistConnectionsResponse:
    """Lists an artist's direct connections, strongest first."""
    artist_id = parse_name(artist, "artists", field="parent")
    graph = model.graph
    require_artist(graph, artist_id)
    kinds = kinds_from(categories)
    flt = node_filter(who, genres, include_unknown_genre=include_unknown_genre, graph=graph)
    adjacency = graph.adjacency(kinds)
    neighbors = [n for n in adjacency[artist_id] if flt.allows(graph.nodes[n])]
    if order_by == "strength desc":
        neighbors.sort(key=lambda n: (-adjacency[artist_id][n], graph.nodes[n].name, n))
    elif order_by == "displayName":
        neighbors.sort(key=lambda n: (graph.nodes[n].name.casefold(), n))
    else:
        raise invalid_argument("orderBy must be `strength desc` or `displayName`.", field="orderBy")
    page = paginate(
        neighbors,
        page_size=page_size,
        page_token=page_token,
        version=model.version,
        params=fingerprint(
            artist_id, sorted(kinds), sorted(flt.genre_ids), order_by, include_unknown_genre
        ),
    )
    connections = []
    for other in page.items:
        edge = graph.edge(artist_id, other)
        assert edge is not None
        explanations = explain_edge(graph, edge, artist_id, kinds)
        connections.append(
            api.Connection(
                artist=convert.artist_summary(graph, other),
                strength=round(adjacency[artist_id][other], 4),
                kinds=convert.kinds_list(e.kind for e in explanations),
                evidence_count=len(explanations),
                highlights=[convert.evidence(e) for e in explanations[:HIGHLIGHTS_PER_CONNECTION]],
            )
        )
    set_cache_control(response, who)
    return api.ListArtistConnectionsResponse(
        connections=connections,
        next_page_token=page.next_page_token,
        total_size=page.total_size,
        graph_version=model.version,
    )


@router.get(
    "/artists/{artist:rid}/connections/{other:rid}",
    response_model=api.ConnectionDetail,
    summary="GetArtistConnection",
)
def get_artist_connection(
    artist: str,
    other: str,
    model: ReadModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    categories: Categories = [],  # noqa: B006
) -> api.ConnectionDetail:
    """Returns every piece of evidence connecting two artists, with sources."""
    artist_id = parse_name(artist, "artists", field="name")
    other_id = parse_name(other, "artists", field="name")
    graph = model.graph
    require_artist(graph, artist_id)
    require_artist(graph, other_id)
    kinds = kinds_from(categories)
    edge = graph.edge(artist_id, other_id)
    explanations = explain_edge(graph, edge, artist_id, kinds) if edge else []
    if edge is None or not explanations:
        raise not_found(
            f"artists/{artist_id}/connections/{other_id}", reason="CONNECTION_NOT_FOUND"
        )
    sources = repo.subject_sources(session, convert.subject_keys(explanations))
    set_cache_control(response, who)
    return api.ConnectionDetail(
        artist=convert.artist_summary(graph, artist_id),
        other=convert.artist_summary(graph, other_id),
        strength=round(edge.strength(kinds), 4),
        kinds=convert.kinds_list(e.kind for e in explanations),
        evidence=[convert.evidence(e, sources) for e in explanations],
        graph_version=model.version,
    )


@router.get(
    "/artists/{artist:rid}/collaborations",
    response_model=api.ListArtistCollaborationsResponse,
    summary="ListArtistCollaborations",
)
def list_artist_collaborations(
    artist: str,
    model: ReadModelDep,
    who: ViewerDep,
    response: Response,
    type_: Annotated[api.CollaborationType, Query(alias="type")] = api.CollaborationType.FEATURE,
    page_size: PageSize = 25,
    page_token: PageToken = "",
) -> api.ListArtistCollaborationsResponse:
    """Lists an artist's collaborators of one type (features, production, bands, credits)."""
    artist_id = parse_name(artist, "artists", field="parent")
    graph = model.graph
    require_artist(graph, artist_id)
    flt = node_filter(who, [], include_unknown_genre=True, graph=graph)
    core_type = convert.collaboration_type(type_)
    items = collab.collaborations(graph, artist_id, core_type, flt)
    page = paginate(
        items,
        page_size=page_size,
        page_token=page_token,
        version=model.version,
        params=fingerprint(artist_id, type_.value),
    )
    kinds = collab.TYPE_KINDS[core_type]
    results = []
    for item in page.items:
        edge = graph.edge(artist_id, item.artist_id)
        assert edge is not None
        results.append(
            api.Collaboration(
                artist=convert.artist_summary(graph, item.artist_id),
                type=type_,
                count=item.count,
                first_year=item.first_year,
                last_year=item.last_year,
                evidence=[convert.evidence(e) for e in explain_edge(graph, edge, artist_id, kinds)],
            )
        )
    counts = collab.collaboration_counts(graph, artist_id, flt)
    set_cache_control(response, who)
    return api.ListArtistCollaborationsResponse(
        collaborations=results,
        counts={api.CollaborationType(t.value): n for t, n in counts.items()},
        next_page_token=page.next_page_token,
        total_size=page.total_size,
        graph_version=model.version,
    )


@router.get("/recordings/{recording:rid}", response_model=api.Recording, summary="GetRecording")
def get_recording(
    recording: str, model: ReadModelDep, who: ViewerDep, session: SessionDep, response: Response
) -> api.Recording:
    """Returns a recording with its credits and the releases it appears on."""
    recording_id = parse_name(recording, "recordings", field="name")
    details = repo.recording_details(session, recording_id)
    if details is None:
        raise not_found(f"recordings/{recording_id}", reason="RECORDING_NOT_FOUND")
    graph = model.graph
    set_cache_control(response, who)
    return api.Recording(
        name=f"recordings/{details.id}",
        display_name=details.title,
        length_ms=details.length_ms,
        first_release_date=details.first_release_date,
        credits=[
            api.Credit(
                artist=convert.artist_summary(graph, c.artist_id),
                role=c.role,
                role_detail=c.role_detail,
                credited_as=c.credited_as,
            )
            for c in details.credits
            if c.artist_id in graph.nodes and c.artist_id not in who.blocked
        ],
        appearances=[
            api.Appearance(
                release=f"releases/{a.release_id}",
                display_name=a.title,
                year=a.year,
                disc_number=a.disc_number,
                position=a.position,
            )
            for a in details.appearances
        ],
        sources=convert.source_links(details.sources),
    )


@router.get("/catalog:search", response_model=api.SearchCatalogResponse, summary="SearchCatalog")
def search_catalog(
    model: ReadModelDep,
    who: ViewerDep,
    response: Response,
    query: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH)],
    types: Annotated[list[api.EntityType], Query()] = [],  # noqa: B006
    page_size: Annotated[int, Query(alias="pageSize", ge=0, le=50)] = 10,
) -> api.SearchCatalogResponse:
    """Searches artists, releases and recordings by name, in any script."""
    entity_types = frozenset(CoreEntityType(t.value.lower()) for t in types) or None
    hits = model.search.search(query, limit=page_size or 10, entity_types=entity_types)
    # Blocked artists never appear as suggestions, except as an exact-name match,
    # flagged so the client can offer to unblock (AC-17.2).
    hits = [h for h in hits if h.entity_id not in who.blocked or h.match_type is MatchType.EXACT]
    collections = {"artist": "artists", "release": "releases", "recording": "recordings"}
    set_cache_control(response, who)
    return api.SearchCatalogResponse(
        results=[
            api.SearchResult(
                name=f"{collections[h.entity_type.value]}/{h.entity_id}",
                entity_type=api.EntityType(h.entity_type.value.upper()),
                display_name=h.name,
                subtitle=h.subtitle,
                match_type=h.match_type.value,
                matched_on=h.matched_on,
                blocked=h.entity_id in who.blocked,
            )
            for h in hits
        ],
        graph_version=model.version,
    )


@router.get("/genres", response_model=api.ListGenresResponse, summary="ListGenres")
def list_genres(
    model: ReadModelDep,
    session: SessionDep,
    response: Response,
    page_size: PageSize = 100,
    page_token: PageToken = "",
) -> api.ListGenresResponse:
    """Lists genres by how many artists carry them."""
    genres = repo.genre_counts(session)
    page = paginate(
        genres, page_size=page_size, page_token=page_token, version=model.version, params="genres"
    )
    set_cache_control(response, None)
    return api.ListGenresResponse(
        genres=[
            api.Genre(name=f"genres/{g.id}", display_name=g.name, artist_count=g.artist_count)
            for g in page.items
        ],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )
