"""Around you: campus and city communities, their charts, and the listener's memberships.

Listeners opt in to one campus and one city (``users/{user}/communities``); writes
check Origin and the CSRF token and are audited like every user write. Charts are
public and anonymous: built from opted-in members' linked-account tallies, shown
only past the privacy floors in ``core.community``, with counts as ranges.
The ``community`` flag switches every method here off (export and account
deletion still cover memberships).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from songnexus.catalog.communities import load_directory
from songnexus.core import community as core
from songnexus.logs import request_id_var
from songnexus.service import community_job, convert
from songnexus.service import schemas_community as api
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    check_write_origin,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.pagination import paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import (
    MAX_QUERY_LENGTH,
    PageSize,
    PageToken,
    db_session,
    set_cache_control,
)
from songnexus.storage import community_repository as repo
from songnexus.storage import user_repository as users

router = APIRouter(prefix="/v1", tags=["community"])

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ReadModelDep = Annotated[ReadModel, Depends(read_model)]
Write = [Depends(rate_limited(MethodClass.WRITE))]
Read = [Depends(rate_limited(MethodClass.READ))]

MEMBERSHIP_FIELDS = frozenset({"campus", "city"})
_KIND_OF_FIELD = {"campus": core.Kind.CAMPUS, "city": core.Kind.CITY}


def _enabled(request: Request) -> None:
    if not app_state(request).flags.get("community", True):
        raise ApiError(Status.UNAVAILABLE, "Around you is switched off.", reason="FLAG_OFF")


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _audit(session: Session, user_id: str, action: str) -> None:
    users.audit(session, user_id, action, request_id_var.get(), datetime.now(UTC))


def community_resource(c: core.Community) -> api.Community:
    """Returns the API form of a community."""
    return api.Community(
        name=f"communities/{c.id}",
        kind=api.CommunityKind(c.kind.value),
        display_name=c.name,
        short_name=c.short_name,
        city=c.city,
        region=c.region,
        country=c.country,
        website=c.website,
        city_community=f"communities/{c.city_id}" if c.city_id else None,
        source_url=f"https://www.wikidata.org/wiki/{c.wikidata}" if c.wikidata else "",
        synthetic=c.synthetic,
    )


def _community(value: str, field: str = "name") -> core.Community:
    """Resolves ``communities/{id}`` or a bare ID.

    Raises:
        ApiError: NOT_FOUND for an unknown community.
    """
    community_id = value.removeprefix("communities/")
    found = load_directory().by_id.get(community_id)
    if found is None:
        if not community_id or "/" in community_id:
            raise invalid_argument(
                f"{field} must be a resource name like `communities/{{id}}`.", field=field
            )
        raise not_found(f"communities/{community_id}", reason="COMMUNITY_NOT_FOUND")
    return found


def _range(count: int) -> api.ListenerRange:
    found = core.band(count)
    if found is None:  # never happens past the floors; fail closed rather than leak
        raise ApiError(Status.INTERNAL, "Chart floor violated.", reason="CHART_FLOOR")
    return api.ListenerRange(min=found.low, max=found.high)


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------


@router.get(
    "/communities",
    response_model=api.ListCommunitiesResponse,
    summary="ListCommunities",
    dependencies=Read,
)
def list_communities(
    request: Request,
    response: Response,
    query: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)] = "",
    kind: api.CommunityKind | None = None,
    country: Annotated[str, Query(pattern="^$|^[A-Z]{2}$")] = "",
    synthetic: bool | None = None,
    page_size: PageSize = 20,
    page_token: PageToken = "",
) -> api.ListCommunitiesResponse:
    """Searches the campuses and cities listeners can join (largest first when no query)."""
    _enabled(request)
    directory = load_directory()
    found = directory.search(query, core.Kind(kind.value) if kind else None)
    found = [
        c
        for c in found
        if (not country or c.country == country) and (synthetic is None or c.synthetic == synthetic)
    ]
    page = paginate(
        found,
        page_size=page_size,
        page_token=page_token,
        version=directory.version,
        params=f"communities:{query}:{kind}:{country}:{synthetic}",
    )
    set_cache_control(response, None)
    return api.ListCommunitiesResponse(
        communities=[community_resource(c) for c in page.items],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )


@router.get(
    "/communities/{community:rid}",
    response_model=api.Community,
    summary="GetCommunity",
    dependencies=Read,
)
def get_community(community: str, request: Request, response: Response) -> api.Community:
    """Returns one campus or city."""
    _enabled(request)
    found = _community(community)
    set_cache_control(response, None)
    return community_resource(found)


@router.get(
    "/communities/{community:rid}/chart",
    response_model=api.CommunityChart,
    summary="GetCommunityChart",
    dependencies=Read,
)
def get_community_chart(
    community: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> api.CommunityChart:
    """What a community listens to: top artists, rising, genres. Anonymous aggregates only.

    Locked (fewer than 10 members with listening data): only how many more are
    needed. Artists and genres need 3 listeners each; counts are ranges.
    """
    _enabled(request)
    found = _community(community)
    now = datetime.now(UTC)
    view = community_job.chart_view(session, app_state(request).settings, model, found.id, now)
    chart = view.chart
    graph = model.graph
    previous = core.baseline(view.history, now)
    moves = core.movements(chart, previous)
    rising_ids = core.rising(chart, view.history, now) if chart.unlocked else []
    rising_set = set(rising_ids)

    def row(item: core.ArtistRow) -> api.CommunityChartArtist:
        move = moves.get(item.artist_id) if moves is not None else None
        return api.CommunityChartArtist(
            rank=item.rank,
            artist=convert.artist_summary(graph, item.artist_id),
            listeners=_range(item.listeners),
            movement=api.ChartMovement(move.direction.value) if move else None,
            places=move.places if move else 0,
            rising=item.artist_id in rising_set,
        )

    # The viewer's blocked artists are hidden; ranks are kept as computed.
    visible = [
        a for a in chart.artists if a.artist_id in graph.nodes and a.artist_id not in who.blocked
    ]
    by_id = {a.artist_id: a for a in visible}
    set_cache_control(response, who)
    return api.CommunityChart(
        name=f"communities/{found.id}/chart",
        community=community_resource(found),
        state=api.ChartState.UNLOCKED if chart.unlocked else api.ChartState.LOCKED,
        listeners_needed=chart.listeners_needed,
        min_listeners=core.MIN_CHART_LISTENERS,
        min_artist_listeners=core.MIN_ARTIST_LISTENERS,
        listeners=_range(chart.eligible) if chart.unlocked else None,
        artists=[row(a) for a in visible],
        rising=[row(by_id[a]) for a in rising_ids if a in by_id],
        genres=[
            api.CommunityChartGenre(
                genre=f"genres/{g.genre_id}",
                display_name=graph.genre_names.get(g.genre_id, g.genre_id),
                listeners=_range(g.listeners),
            )
            for g in chart.genres
            if g.genre_id in graph.genre_names
        ],
        history_available=previous is not None,
        demo_data=chart.demo,
        update_time=_time(chart.computed_at),
        next_update_time=_time(view.next_update),
        graph_version=model.version,
    )


# ---------------------------------------------------------------------------
# The listener's memberships
# ---------------------------------------------------------------------------


def _memberships(session: Session, user_id: str) -> api.UserCommunities:
    rows = repo.memberships(session, user_id)
    directory = load_directory()

    def membership(kind: core.Kind) -> api.CommunityMembership | None:
        row = rows.get(kind.value)
        found = directory.by_id.get(row.community_id) if row else None
        if row is None or found is None:  # a community dropped from the directory
            return None
        return api.CommunityMembership(
            community=community_resource(found), join_time=_time(row.joined_at)
        )

    return api.UserCommunities(
        name=f"users/{user_id}/communities",
        campus=membership(core.Kind.CAMPUS),
        city=membership(core.Kind.CITY),
        has_listening_data=repo.has_listening(session, user_id),
    )


@router.get(
    "/users/{user:rid}/communities",
    response_model=api.UserCommunities,
    summary="GetUserCommunities",
    dependencies=Read,
)
def get_user_communities(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.UserCommunities:
    """Returns the campus and city the listener joined (none until they opt in)."""
    _enabled(request)
    user_id = authorize_user(user, who)
    _private(response)
    return _memberships(session, user_id)


@router.patch(
    "/users/{user:rid}/communities",
    response_model=api.UserCommunities,
    summary="UpdateUserCommunities",
    dependencies=Write,
)
def update_user_communities(
    user: str,
    body: api.UpdateUserCommunitiesRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    update_mask: Annotated[str | None, Query(alias="updateMask")] = None,
) -> api.UserCommunities:
    """Joins, switches or leaves (empty value) a campus or city. Leaving deletes it now."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    if update_mask is None:
        fields = set(body.model_fields_set) & MEMBERSHIP_FIELDS
    else:
        fields = {f.strip() for f in update_mask.split(",") if f.strip()}
        unknown = sorted(fields - MEMBERSHIP_FIELDS)
        if unknown:
            raise invalid_argument(
                f"Unknown field in updateMask: {unknown[0]}.", field="updateMask"
            )
    if not fields:
        raise invalid_argument("Name campus or city in updateMask.", field="updateMask")
    now = datetime.now(UTC)
    for field_name in sorted(fields):
        kind = _KIND_OF_FIELD[field_name]
        value = str(getattr(body, field_name)).strip()
        if not value:
            if repo.leave(session, user_id, kind.value):
                _audit(session, user_id, "community.leave")
            continue
        found = _community(value, field=field_name)
        if found.kind is not kind:
            raise invalid_argument(
                f"communities/{found.id} is not a {kind.value.lower()}.", field=field_name
            )
        repo.join(session, user_id, kind.value, found.id, now)
        _audit(session, user_id, "community.join")
    session.flush()
    _private(response)
    return _memberships(session, user_id)
