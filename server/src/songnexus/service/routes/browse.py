"""Browse methods: home shelves, genre pages, explained recommendations, taste profiles.

Everything here is derived from the catalog: counts over credits, the artist
graph and aggregate listening. The browse index is built once per catalog
version (like stories) and anonymous responses are served from the response
cache; signed-in viewers get the same data minus the artists they blocked.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from songnexus.core import game, taste
from songnexus.core import recommend as rec
from songnexus.core import shelves as shelf_core
from songnexus.core.browse import BrowseIndex, build_index, genre_share, step_track
from songnexus.core.graph.model import EdgeKind
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service import schemas_browse as br
from songnexus.service.cache import cached_anonymous
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    parse_name,
    rate_limited,
    read_model,
    require_artist,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.pagination import fingerprint, paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import PageSize, PageToken, db_session, set_cache_control
from songnexus.storage import accounts_repository
from songnexus.storage.browse_reader import read_browse_facts

router = APIRouter(prefix="/v1", tags=["browse"])

ModelDep = Annotated[ReadModel, Depends(read_model)]
ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
Read = [Depends(rate_limited(MethodClass.READ))]
Analyze = [Depends(rate_limited(MethodClass.ANALYZE))]

ITEMS_PER_SHELF = 12
# A home row with one or two items looks broken; such shelves are left out.
MIN_SHELF_ITEMS = 3
DEFAULT_RECOMMENDATIONS = 20
LISTENBRAINZ = api.SourceLink(
    source="dataSources/listenbrainz", source_id="", url="https://listenbrainz.org/"
)


def _flag(name: str) -> Callable[[Request], None]:
    def check(request: Request) -> None:
        if not app_state(request).flags.get(name, True):
            raise ApiError(Status.UNAVAILABLE, "This feature is switched off.", reason="FLAG_OFF")

    return check


def browse_index(model: ReadModel, session: Session) -> BrowseIndex:
    """Returns the browse index for the model's catalog version (built on first use)."""
    return model.memo.get(
        "browse_index", lambda: build_index(model.graph, read_browse_facts(session))
    )


def _day(value: str, today: date | None = None) -> date:
    """Parses the viewer's local date, accepted from launch up to UTC today + 1.

    The same window as the daily puzzle: local dates run up to 14 hours ahead of UTC.

    Raises:
        ApiError: INVALID_ARGUMENT for a malformed date or one outside the window.
    """
    try:
        day = date.fromisoformat(value)
        if day.isoformat() != value:
            raise ValueError("non-canonical date")
    except ValueError as exc:
        raise invalid_argument("The date must be YYYY-MM-DD.", field="date") from exc
    latest = (today or datetime.now(UTC).date()) + timedelta(days=1)
    if not game.LAUNCH_DAY <= day <= latest:
        raise invalid_argument(
            "That date is outside the accepted window.", field="date", reason="DATE_NOT_AVAILABLE"
        )
    return day


def path_tracks(
    index: BrowseIndex, path: Sequence[str], kinds: frozenset[EdgeKind], who: Viewer
) -> list[api.PathTrack | None]:
    """One recording per step of a path, avoiding repeats, for FindPath's playlist view."""
    used: set[str] = set()
    tracks: list[api.PathTrack | None] = []
    for u, v in itertools.pairwise(path):
        pick = step_track(index, u, v, kinds, avoid=frozenset(used))
        if pick is None:
            tracks.append(None)
            continue
        used.add(pick.recording_id)
        recording = index.recordings[pick.recording_id]
        tracks.append(
            api.PathTrack(
                recording=f"recordings/{recording.id}",
                display_name=recording.title,
                artists=[
                    convert.artist_summary(index.graph, a)
                    for a in index.primary_artists.get(recording.id, ())
                    if a not in who.blocked
                ],
                year=recording.year,
                first_release_date=recording.date,
                release=None if pick.release_id is None else f"releases/{pick.release_id}",
            )
        )
    return tracks


def _params(params: tuple[tuple[str, str | int], ...]) -> dict[str, str | int]:
    return dict(params)


def _reason(reason: shelf_core.Reason) -> br.Reason:
    return br.Reason(
        kind=br.ShelfReasonKind(reason.kind.value),
        message_id=reason.message_id,
        params=_params(reason.params),
    )


def _recording(index: BrowseIndex, recording_id: str) -> br.ShelfRecording:
    recording = index.recordings[recording_id]
    return br.ShelfRecording(
        name=f"recordings/{recording_id}",
        display_name=recording.title,
        year=recording.year,
        first_release_date=recording.date,
        artists=[
            convert.artist_summary(index.graph, a) for a in index.primary_artists[recording_id]
        ],
    )


def _label(index: BrowseIndex, label_id: str) -> br.ShelfLabel:
    return br.ShelfLabel(name=f"labels/{label_id}", display_name=index.labels[label_id].name)


def _shelf(index: BrowseIndex, shelf: shelf_core.Shelf, who: Viewer) -> br.Shelf | None:
    items: list[br.ShelfItem] = []
    for item in shelf.items:
        if who.blocked.intersection(item.artist_ids):
            continue
        items.append(
            br.ShelfItem(
                artist=None
                if item.artist_id is None
                else convert.artist_summary(index.graph, item.artist_id),
                recording=None
                if item.recording_id is None
                else _recording(index, item.recording_id),
                label=None if item.label_id is None else _label(index, item.label_id),
                reason=_reason(item.reason),
            )
        )
        if len(items) == ITEMS_PER_SHELF:
            break
    if len(items) < MIN_SHELF_ITEMS:
        return None
    return br.Shelf(
        name=f"shelves/{shelf.id}",
        kind=br.ShelfKind(shelf.kind.value),
        message_id=shelf.message_id,
        params=_params(shelf.params),
        genre=None if shelf.genre_id is None else f"genres/{shelf.genre_id}",
        items=items,
    )


@router.get(
    "/shelves",
    response_model=br.ListShelvesResponse,
    summary="ListShelves",
    dependencies=[*Read, Depends(_flag("browse"))],
)
@cached_anonymous
def list_shelves(
    request: Request,
    model: ModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    date: Annotated[
        str | None,
        Query(
            description="The viewer's local date (YYYY-MM-DD), for the ON_THIS_DAY shelf. "
            "Accepted in the daily puzzle's window; without it there is no ON_THIS_DAY shelf.",
            max_length=10,
        ),
    ] = None,
) -> br.ListShelvesResponse:
    """Lists the home page's shelves, in display order, each item with its reason.

    The same for everyone for a catalog version and date, minus the artists a
    signed-in viewer blocked. Shelves with fewer than three items are left out.
    """
    index = browse_index(model, session)
    catalog = model.memo.get("shelves", lambda: shelf_core.catalog_shelves(index))
    today = None
    if date is not None:
        day = _day(date)
        today = model.memo.get(
            f"shelves:on-this-day:{day.isoformat()}", lambda: shelf_core.on_this_day(index, day)
        )
    shelves = [_shelf(index, s, who) for s in shelf_core.home_shelves(catalog, today)]
    set_cache_control(response, who)
    return br.ListShelvesResponse(
        shelves=[s for s in shelves if s is not None], graph_version=model.version
    )


def _genre_id(model: ReadModel, genre: str) -> str:
    genre_id = parse_name(genre, "genres", field="name")
    if genre_id not in model.graph.genre_names:
        raise not_found(f"genres/{genre_id}", reason="GENRE_NOT_FOUND")
    return genre_id


def _genre_ref(model: ReadModel, genre_id: str) -> br.GenreRef:
    direct, total = model.graph.genre_artist_counts().get(genre_id, (0, 0))
    return br.GenreRef(
        name=f"genres/{genre_id}",
        display_name=model.graph.genre_names[genre_id],
        artist_count=direct,
        artist_count_with_subgenres=total,
    )


def _genre_members(
    model: ReadModel, index: BrowseIndex, genre_id: str, include_subgenres: bool
) -> list[str]:
    return model.memo.get(
        f"genre_artists:{genre_id}:{int(include_subgenres)}",
        lambda: index.genre_artists(genre_id, include_subgenres=include_subgenres),
    )


@router.get(
    "/genres/{genre:rid}",
    response_model=br.GenreDetail,
    summary="GetGenre",
    dependencies=[*Read, Depends(_flag("browse"))],
)
@cached_anonymous
def get_genre(
    request: Request, genre: str, model: ModelDep, session: SessionDep, response: Response
) -> br.GenreDetail:
    """Returns a genre: its parents, its subgenres with artists, and its artist counts."""
    genre_id = _genre_id(model, genre)
    graph = model.graph
    counts = graph.genre_artist_counts()
    index = browse_index(model, session)
    parents = sorted(graph.genre_parents.get(genre_id, ()), key=lambda g: graph.genre_names[g])
    children = sorted(
        (c for c in graph.genre_children(genre_id) if c in counts),
        key=lambda c: (-counts[c][1], graph.genre_names[c], c),
    )
    direct, total = counts.get(genre_id, (0, 0))
    set_cache_control(response, None)
    return br.GenreDetail(
        name=f"genres/{genre_id}",
        display_name=graph.genre_names[genre_id],
        artist_count=direct,
        artist_count_with_subgenres=total,
        member_count=len(_genre_members(model, index, genre_id, True)),
        top_level=not parents,
        parents=[_genre_ref(model, p) for p in parents],
        children=[_genre_ref(model, c) for c in children],
        graph_version=model.version,
    )


@router.get(
    "/genres/{genre:rid}/artists",
    response_model=br.ListGenreArtistsResponse,
    summary="ListGenreArtists",
    dependencies=[*Read, Depends(_flag("browse"))],
)
@cached_anonymous
def list_genre_artists(
    request: Request,
    genre: str,
    model: ModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    include_subgenres: Annotated[
        bool, Query(alias="includeSubgenres", description="Count artists of subgenres too.")
    ] = True,
    page_size: PageSize = 25,
    page_token: PageToken = "",
) -> br.ListGenreArtistsResponse:
    """Lists a genre's artists, most connected first.

    An artist is in the genre when at least 20% of its genre shares fall in the
    genre (or, by default, its subgenres): the genre filter's rule.
    """
    genre_id = _genre_id(model, genre)
    graph = model.graph
    index = browse_index(model, session)
    members = [
        a for a in _genre_members(model, index, genre_id, include_subgenres) if a not in who.blocked
    ]
    page = paginate(
        members,
        page_size=page_size,
        page_token=page_token,
        version=model.version,
        params=fingerprint("genreArtists", genre_id, include_subgenres, sorted(who.blocked)),
    )
    genres = graph.with_subgenres([genre_id]) if include_subgenres else frozenset([genre_id])
    set_cache_control(response, who)
    return br.ListGenreArtistsResponse(
        artists=[
            br.GenreArtist(
                artist=convert.artist_summary(graph, a),
                collaborator_count=index.degree[a],
                genre_share=round(min(1.0, genre_share(graph.nodes[a].genres, genres)), 4),
            )
            for a in page.items
        ],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
        graph_version=model.version,
    )


def _allowed(who: Viewer) -> Callable[[str], bool] | None:
    blocked = who.blocked
    return None if not blocked else (lambda artist_id: artist_id not in blocked)


def _recommendation(index: BrowseIndex, item: rec.Recommendation) -> br.Recommendation:
    graph = index.graph
    reasons = []
    for kind in item.reasons:
        reason = br.RecommendationReason(
            kind=br.RecommendationReasonKind(kind.value),
            message_id=rec.REASON_MESSAGES[kind],
        )
        if kind is rec.ReasonKind.SHARED_COLLABORATORS:
            reason = reason.model_copy(
                update={
                    "params": {"count": item.shared_count},
                    "via": [convert.artist_summary(graph, v) for v in item.via],
                }
            )
        elif kind is rec.ReasonKind.LISTENERS_IN_COMMON:
            assert item.listening_rank is not None
            assert item.listening_strength is not None
            reason = reason.model_copy(
                update={
                    "params": {
                        "rank": item.listening_rank,
                        "strength": item.listening_strength.value,
                    },
                    "source": LISTENBRAINZ,
                }
            )
        else:
            assert item.label_id is not None
            reason = reason.model_copy(
                update={
                    "params": {"label": index.labels[item.label_id].name},
                    "label": _label(index, item.label_id),
                }
            )
        reasons.append(reason)
    return br.Recommendation(
        artist=convert.artist_summary(graph, item.artist_id),
        score=round(item.score, 4),
        reasons=reasons,
    )


@router.get(
    "/artists/{artist:rid}:recommend",
    response_model=br.RecommendArtistsResponse,
    summary="RecommendArtists",
    dependencies=[*Analyze, Depends(_flag("recommendations"))],
)
@cached_anonymous
def recommend_artists(
    request: Request,
    artist: str,
    model: ModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
    page_size: Annotated[
        int, Query(alias="pageSize", ge=0, le=rec.MAX_RECOMMENDATIONS)
    ] = DEFAULT_RECOMMENDATIONS,
) -> br.RecommendArtistsResponse:
    """Recommends artists not directly connected to this one, each with checkable reasons.

    Reasons are shared collaborators (up to three named, and the count),
    listeners in common (aggregate co-listening, above the privacy floor) or a
    shared label. An artist with no reason is never recommended. The artist
    asked about is the viewer's choice and is allowed even when blocked.
    """
    artist_id = parse_name(artist, "artists", field="name")
    graph = model.graph
    require_artist(graph, artist_id)
    index = browse_index(model, session)
    items = rec.recommend(
        index, artist_id, allowed=_allowed(who), limit=page_size or DEFAULT_RECOMMENDATIONS
    )
    set_cache_control(response, who)
    return br.RecommendArtistsResponse(
        artist=convert.artist_summary(graph, artist_id),
        recommendations=[_recommendation(index, item) for item in items],
        graph_version=model.version,
    )


def _profile(
    index: BrowseIndex, result: taste.TasteProfile, skipped: int, version: str
) -> br.TasteProfile:
    graph = index.graph

    def summary(artist_id: str) -> api.ArtistSummary:
        return convert.artist_summary(graph, artist_id)

    pair = result.surprising_pair
    cluster = result.cluster
    return br.TasteProfile(
        artist_count=len(result.artist_ids),
        skipped_artist_count=skipped,
        genres=[
            br.TasteGenre(
                genre=f"genres/{s.key}",
                display_name=graph.genre_names[s.key],
                share=round(s.share, 4),
                artist_count=s.artist_count,
            )
            for s in result.genres
        ],
        unknown_genre_artist_count=result.unknown_genre_artists,
        decades=[
            br.TasteDecade(decade=int(s.key), share=round(s.share, 4), artist_count=s.artist_count)
            for s in result.decades
        ],
        undated_artist_count=result.undated_artists,
        most_central=None
        if result.central is None
        else br.TasteCentral(artist=summary(result.central[0]), linked_count=result.central[1]),
        hidden_connectors=[
            br.TasteConnector(
                artist=summary(c.artist_id),
                linked_count=len(c.linked),
                linked_to=[f"artists/{a}" for a in c.linked],
            )
            for c in result.connectors
        ],
        tightest_cluster=None
        if cluster is None
        else br.TasteCluster(
            artists=[summary(a) for a in cluster.artist_ids],
            size=cluster.size,
            min_links=cluster.min_links,
            links=cluster.links,
        ),
        surprising_pair=None
        if pair is None
        else br.TastePair(artist_a=summary(pair.a), artist_b=summary(pair.b), steps=pair.steps),
        collaborators_reached=result.collaborators_reached,
        graph_version=version,
    )


@router.post(
    "/tasteProfiles:compute",
    response_model=br.TasteProfile,
    summary="ComputeTasteProfile",
    dependencies=[*Analyze, Depends(_flag("tasteProfile"))],
)
def compute_taste_profile(
    body: br.ComputeTasteProfileRequest,
    model: ModelDep,
    who: ViewerDep,
    session: SessionDep,
    response: Response,
) -> br.TasteProfile:
    """Profiles a list of artists ("Your Nexus") without storing anything.

    For signed-out listeners who matched a playlist on their device: send the
    matched artists' resource names, most important first. Artists not in the
    catalog, or blocked, are skipped and counted.
    """
    requested = list(
        dict.fromkeys(parse_name(name, "artists", field="artists") for name in body.artists)
    )
    graph = model.graph
    weights = {a: 1.0 for a in requested if a in graph.nodes and a not in who.blocked}
    index = browse_index(model, session)
    result = taste.profile(index, weights, allowed=_allowed(who))
    response.headers["Cache-Control"] = "private, no-store"
    return _profile(index, result, len(requested) - len(result.artist_ids), model.version)


@router.get(
    "/users/{user:rid}/tasteProfile",
    response_model=br.TasteProfile,
    summary="GetTasteProfile",
    dependencies=[*Analyze, Depends(_flag("tasteProfile"))],
)
def get_taste_profile(
    user: str, model: ModelDep, who: ViewerDep, session: SessionDep, response: Response
) -> br.TasteProfile:
    """The signed-in listener's profile, from the artists their linked accounts played.

    Artists are weighted by 1 + ln(plays). Without listening data every part is empty.
    """
    user_id = authorize_user(user, who)
    graph = model.graph
    plays: dict[str, int] = {}
    for tally in accounts_repository.listening(session, user_id):
        if tally.artist_id in graph.nodes and tally.artist_id not in who.blocked:
            plays[tally.artist_id] = plays.get(tally.artist_id, 0) + tally.plays
    ordered = sorted(plays, key=lambda a: (-plays[a], graph.nodes[a].name, a))
    weights = {a: taste.play_weight(plays[a]) for a in ordered}
    index = browse_index(model, session)
    result = taste.profile(index, weights, allowed=_allowed(who))
    response.headers["Cache-Control"] = "private, no-store"
    return _profile(index, result, len(ordered) - len(result.artist_ids), model.version)
