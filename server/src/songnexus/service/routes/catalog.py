"""Catalog methods: artists, connections, collaborations, labels, recordings, search, genres."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from songnexus.core.graph import collaborations as collab
from songnexus.core.graph.algorithms import bidirectional_bfs_path
from songnexus.core.graph.explain import explain_edge
from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import DEFAULT_CATEGORIES, EdgeKind, kinds_for
from songnexus.core.search import EntityType as CoreEntityType
from songnexus.core.search import MatchType
from songnexus.core.songs import Descriptors, shared_credits, similarity
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
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
    MAX_PATH_STEPS,
    MAX_QUERY_LENGTH,
    GenreSelectionDep,
    PageSize,
    PageToken,
    db_session,
    selection_filter,
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

HIGHLIGHTS_PER_CONNECTION = 2
# Genres shown on an artist page; the graph keeps more for filtering.
DISPLAY_GENRES = 5
OFTEN_PLAYED_WITH = 10


def kinds_from(categories: list[api.ConnectionCategory]) -> frozenset[EdgeKind]:
    """Returns the enabled edge kinds for requested categories (defaults when empty)."""
    if not categories:
        return kinds_for(DEFAULT_CATEGORIES)
    return kinds_for(convert.category(c) for c in categories)


@router.get("/artists/{artist:rid}", response_model=api.Artist, summary="GetArtist")
def get_artist(
    artist: str, model: ReadModelDep, session: SessionDep, response: Response
) -> api.Artist:
    """Returns an artist with genres, aliases, links, labels and sources."""
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
                genre=f"genres/{g.genre_id}",
                display_name=g.name,
                share=round(g.share, 4),
                sources=[f"dataSources/{s}" for s in g.sources],
            )
            for g in node.genres[:DISPLAY_GENRES]
        ],
        aliases=[
            api.Alias(display_name=a.name, alias_type=a.alias_type, locale=a.locale)
            for a in details.aliases
        ],
        links=[api.Link(link_type=link.link_type, url=link.url) for link in details.links],
        connection_count=len(graph.adjacency(kinds_for(DEFAULT_CATEGORIES))[artist_id]),
        labels=[
            api.ArtistLabel(
                label=f"labels/{lb.label_id}",
                display_name=lb.name,
                release_count=lb.release_count,
                first_year=lb.first_year,
                last_year=lb.last_year,
            )
            for lb in repo.artist_labels(session, artist_id)
        ],
        often_played_with=[
            api.CoListener(artist=convert.artist_summary(graph, other), rank=rank)
            for other, rank in repo.colisteners(session, artist_id, OFTEN_PLAYED_WITH)
            if other in graph.nodes
        ],
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
    genre_filter: GenreSelectionDep,
    categories: Categories = [],  # noqa: B006 - FastAPI copies query defaults
    order_by: Annotated[str, Query(alias="orderBy")] = "strength desc",
    page_size: PageSize = 25,
    page_token: PageToken = "",
) -> api.ListArtistConnectionsResponse:
    """Lists an artist's direct connections, strongest first."""
    artist_id = parse_name(artist, "artists", field="parent")
    graph = model.graph
    require_artist(graph, artist_id)
    kinds = kinds_from(categories)
    flt = selection_filter(who, genre_filter, graph)
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
            artist_id,
            sorted(kinds),
            sorted(flt.genre_ids),
            order_by,
            genre_filter.include_unknown_genre,
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
    genre_filter: GenreSelectionDep,
    type_: Annotated[api.CollaborationType, Query(alias="type")] = api.CollaborationType.FEATURE,
    direction: Annotated[
        api.ProductionDirection | None,
        Query(description="With type PRODUCTION: only collaborations that went this way."),
    ] = None,
    start_year: Annotated[
        int | None,
        Query(alias="startYear", ge=1000, le=3000, description="Only evidence from this year on."),
    ] = None,
    end_year: Annotated[
        int | None,
        Query(alias="endYear", ge=1000, le=3000, description="Only evidence up to this year."),
    ] = None,
    order_by: Annotated[
        api.CollaborationOrder, Query(alias="orderBy")
    ] = api.CollaborationOrder.COUNT,
    page_size: PageSize = 25,
    page_token: PageToken = "",
) -> api.ListArtistCollaborationsResponse:
    """Lists an artist's collaborators of one type (features, production, bands, credits).

    A genre filter keeps collaborators in the selected genres (and, by default, their subgenres).
    """
    artist_id = parse_name(artist, "artists", field="parent")
    graph = model.graph
    require_artist(graph, artist_id)
    flt = selection_filter(who, genre_filter, graph)
    core_type = convert.collaboration_type(type_)
    if direction is not None and core_type is not collab.CollaborationType.PRODUCTION:
        raise invalid_argument("direction applies only to type PRODUCTION.", field="direction")
    core_direction = None if direction is None else collab.ProductionDirection(direction.value)
    if start_year is not None and end_year is not None and start_year > end_year:
        raise invalid_argument("startYear must not be after endYear.", field="startYear")
    years = (
        None if start_year is None and end_year is None else collab.YearRange(start_year, end_year)
    )
    items = collab.collaborations(
        graph,
        artist_id,
        core_type,
        flt,
        direction=core_direction,
        years=years,
        order=collab.CollaborationOrder(order_by.value),
    )
    page = paginate(
        items,
        page_size=page_size,
        page_token=page_token,
        version=model.version,
        params=fingerprint(
            artist_id,
            type_.value,
            direction,
            start_year,
            end_year,
            order_by,
            sorted(flt.genre_ids),
            genre_filter.include_unknown_genre,
        ),
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
                evidence=[
                    convert.evidence(e)
                    for e in explain_edge(graph, edge, artist_id, kinds)
                    if core_direction is None or e.subject_id in _item_subjects(item)
                ],
                directions=sorted(api.ProductionDirection(d.value) for d in item.directions),
            )
        )
    counts = collab.collaboration_counts(graph, artist_id, flt, years)
    timeline = collab.collaboration_timeline(graph, artist_id, flt)
    set_cache_control(response, who)
    return api.ListArtistCollaborationsResponse(
        collaborations=results,
        counts={api.CollaborationType(t.value): n for t, n in counts.items()},
        timeline=[
            api.TimelineYear(
                year=year,
                counts={api.CollaborationType(t.value): n for t, n in per_type.items()},
            )
            for year, per_type in timeline.years.items()
        ],
        undated={api.CollaborationType(t.value): n for t, n in timeline.undated.items()},
        next_page_token=page.next_page_token,
        total_size=page.total_size,
        graph_version=model.version,
    )


def _item_subjects(item: collab.Collaboration) -> frozenset[str]:
    """The subjects behind one collaboration (to keep only direction-matching evidence)."""
    return frozenset(e.subject_id for e in item.evidence)


@router.get("/labels/{label:rid}", response_model=api.Label, summary="GetLabel")
def get_label(
    label: str, model: ReadModelDep, who: ViewerDep, session: SessionDep, response: Response
) -> api.Label:
    """Returns a label: its roster by era and its releases in our data.

    The roster lists the primary artists of the label's releases we hold, so it
    is "artists on this label in our data", never a complete roster.
    """
    label_id = parse_name(label, "labels", field="name")
    details = repo.label_details(session, label_id)
    if details is None:
        raise not_found(f"labels/{label_id}", reason="LABEL_NOT_FOUND")
    graph = model.graph

    def visible(artist_id: str) -> bool:
        return artist_id in graph.nodes and artist_id not in who.blocked

    roster: dict[str, list[int | None]] = {}
    for release in details.releases:
        for artist_id in release.artist_ids:
            if visible(artist_id):
                roster.setdefault(artist_id, []).append(release.year)

    def era(artist_id: str) -> tuple[bool, int, str]:
        known = [y for y in roster[artist_id] if y is not None]
        return (not known, min(known, default=0), graph.nodes[artist_id].name)

    set_cache_control(response, who)
    return api.Label(
        name=f"labels/{details.id}",
        display_name=details.name,
        label_type=details.label_type,
        disambiguation=details.disambiguation,
        artists=[
            api.LabelArtist(
                artist=convert.artist_summary(graph, artist_id),
                release_count=len(years),
                first_year=min((y for y in years if y is not None), default=None),
                last_year=max((y for y in years if y is not None), default=None),
            )
            for artist_id, years in sorted(roster.items(), key=lambda kv: era(kv[0]))
        ],
        releases=[
            api.LabelRelease(
                release=f"releases/{r.release_id}",
                display_name=r.title,
                year=r.year,
                catalog_numbers=list(r.catalog_numbers),
                artists=[convert.artist_summary(graph, a) for a in r.artist_ids if visible(a)],
            )
            for r in details.releases
        ],
        sources=convert.source_links(details.sources),
        graph_version=model.version,
    )


def _descriptors(fields: dict[str, Any] | None) -> api.AudioDescriptors | None:
    if fields is None:
        return None
    core = Descriptors.from_fields(fields)
    mbid = fields["source_recording_id"]
    return api.AudioDescriptors(
        bpm=None if core.bpm is None else round(core.bpm, 1),
        key=core.key,
        scale=core.scale,
        key_strength=core.key_strength,
        length_s=core.length_s,
        average_loudness=core.average_loudness,
        dynamic_complexity=core.dynamic_complexity,
        moods={k: round(v, 3) for k, v in (core.moods or {}).items()},
        source=api.SourceLink(
            source=f"dataSources/{fields['source_id']}",
            source_id=mbid,
            url=f"https://acousticbrainz.org/{mbid}",
        ),
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
        descriptors=_descriptors(repo.recording_descriptors(session, recording_id)),
        sources=convert.source_links(details.sources),
    )


@router.get(
    "/recordings/{recording:rid}:compare",
    response_model=api.CompareRecordingsResponse,
    summary="CompareRecordings",
)
def compare_recordings(
    recording: str,
    model: ReadModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    other: Annotated[str, Query(description="Resource name of the recording to compare with.")],
) -> api.CompareRecordingsResponse:
    """Compares two songs: descriptors, an explained similarity, credits, artist path.

    Audio descriptors sit side by side, credits are compared by role, and the
    path shows how the songs' primary artists connect. The similarity is a
    documented weighted mean of named parts (``core.songs``), never an opaque
    model, and is null when AcousticBrainz has no data for either.
    """
    ids_ = (
        parse_name(recording, "recordings", field="name"),
        parse_name(other, "recordings", field="other"),
    )
    graph = model.graph
    details = []
    for recording_id in ids_:
        found = repo.recording_details(session, recording_id)
        if found is None:
            raise not_found(f"recordings/{recording_id}", reason="RECORDING_NOT_FOUND")
        details.append(found)
    a, b = details

    def visible(artist_id: str) -> bool:
        return artist_id in graph.nodes and artist_id not in who.blocked

    def primary(d: repo.RecordingDetails) -> list[str]:
        return [c.artist_id for c in d.credits if c.role == "primary" and visible(c.artist_id)]

    def summary(d: repo.RecordingDetails) -> api.RecordingSummary:
        return api.RecordingSummary(
            name=f"recordings/{d.id}",
            display_name=d.title,
            artists=[convert.artist_summary(graph, x) for x in primary(d)],
            first_release_date=d.first_release_date,
            length_ms=d.length_ms,
        )

    fields = [repo.recording_descriptors(session, d.id) for d in details]
    descriptors_a, descriptors_b = (
        Descriptors() if f is None else Descriptors.from_fields(f) for f in fields
    )
    result = similarity(descriptors_a, descriptors_b)
    credits = shared_credits(
        ((c.artist_id, c.role) for c in a.credits if visible(c.artist_id)),
        ((c.artist_id, c.role) for c in b.credits if visible(c.artist_id)),
    )
    path: list[str] = []
    primaries = primary(a), primary(b)
    if primaries[0] and primaries[1] and primaries[0][0] != primaries[1][0]:
        found_path = bidirectional_bfs_path(
            graph.adjacency(kinds_for(DEFAULT_CATEGORIES)),
            primaries[0][0],
            primaries[1][0],
            max_depth=MAX_PATH_STEPS,
            allowed=NodeFilter(blocked=who.blocked).predicate(graph),
        ).path
        path = list(found_path or [])
    set_cache_control(response, who)

    def people(artist_ids: tuple[str, ...]) -> list[api.ArtistSummary]:
        return [convert.artist_summary(graph, x) for x in artist_ids]

    return api.CompareRecordingsResponse(
        recording_a=summary(a),
        recording_b=summary(b),
        descriptors_a=_descriptors(fields[0]),
        descriptors_b=_descriptors(fields[1]),
        similarity=None if result.score is None else round(result.score, 4),
        parts=[
            api.SimilarityPart(
                name=p.name,
                similarity=round(p.similarity, 4),
                weight=round(p.weight, 4),
                contribution=round(p.contribution, 4),
            )
            for p in result.parts
        ],
        shared_credits=[
            api.SharedCredit(
                role=row.role,
                both=people(row.both),
                only_a=people(row.only_a),
                only_b=people(row.only_b),
            )
            for row in credits
        ],
        artist_path=[convert.artist_summary(graph, x) for x in path],
        graph_version=model.version,
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
    response: Response,
    page_size: PageSize = 100,
    page_token: PageToken = "",
) -> api.ListGenresResponse:
    """Lists genres with artists (directly or through a subgenre), most artists first.

    Counts come from the served graph, so they reflect the configured genre sources.
    """
    graph = model.graph
    counts = graph.genre_artist_counts()
    ordered = sorted(counts, key=lambda g: (-counts[g][1], -counts[g][0], graph.genre_names[g]))
    page = paginate(
        ordered, page_size=page_size, page_token=page_token, version=model.version, params="genres"
    )
    set_cache_control(response, None)
    return api.ListGenresResponse(
        genres=[
            api.Genre(
                name=f"genres/{g}",
                display_name=graph.genre_names[g],
                artist_count=counts[g][0],
                artist_count_with_subgenres=counts[g][1],
                parents=[
                    f"genres/{p}" for p in sorted(graph.genre_parents.get(g, ())) if p in counts
                ],
            )
            for g in page.items
        ],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )
