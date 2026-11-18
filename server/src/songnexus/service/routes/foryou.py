"""For You (ADR 0010): the feed, interaction events, follows, taste feedback, imports.

The feed is made by Z-star (``core.zstar``) once per refresh: the whole ranked
list is stored with the features the ranker saw (``feed_items``), pages are
read from it, and cards that became unwanted since (followed, blocked, "not
interested") are dropped as pages are read. Events name the feed and position
of a card, which is what the ranker trains on.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from songnexus.core.browse import BrowseIndex
from songnexus.core.model import CreditRole
from songnexus.core.zstar import experiments
from songnexus.core.zstar.catalog import Catalog
from songnexus.core.zstar.pipeline import Feed as ZFeed
from songnexus.core.zstar.pipeline import Reason, recommend
from songnexus.core.zstar.signals import Signals
from songnexus.logs import request_id_var
from songnexus.service import convert
from songnexus.service import schemas as api
from songnexus.service import schemas_foryou as fy
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    check_write_origin,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.pagination import decode_token, encode_token
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.browse import browse_index
from songnexus.service.routes.common import db_session
from songnexus.service.zstar_runtime import RANKERS, catalog_view, embeddings_for, load_signals
from songnexus.storage import models as m
from songnexus.storage import user_repository as users
from songnexus.storage import zstar_repository as zr

router = APIRouter(prefix="/v1", tags=["for you"])

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ReadModelDep = Annotated[ReadModel, Depends(read_model)]
Write = [Depends(rate_limited(MethodClass.WRITE))]
Read = [Depends(rate_limited(MethodClass.READ))]
Analyze = [Depends(rate_limited(MethodClass.ANALYZE))]

DEFAULT_PAGE = 10
MAX_PAGE = 50
TRACKS_PER_CARD = 3
CLOCK_SKEW = timedelta(minutes=10)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _audit(session: Session, user_id: str, action: str) -> None:
    users.audit(session, user_id, action, request_id_var.get(), datetime.now(UTC))


def _genre(catalog: Catalog, genre_id: str | None) -> fy.FeedGenre | None:
    if genre_id is None or genre_id not in catalog.genre_names:
        return None
    return fy.FeedGenre(id=genre_id, display_name=catalog.genre_names[genre_id])


def _tracks(index: BrowseIndex, artist_id: str) -> list[fy.FeedTrack]:
    """Up to three of the artist's own recordings, newest first, distinct titles."""
    ids = index.recordings_by_role.get(artist_id, {}).get(CreditRole.PRIMARY.value, set())
    facts = sorted(
        (index.recordings[r] for r in ids if r in index.recordings),
        key=lambda f: (-(f.year or 0), f.title.casefold(), f.id),
    )
    out: list[fy.FeedTrack] = []
    seen: set[str] = set()
    for fact in facts:
        key = fact.title.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(fy.FeedTrack(name=f"recordings/{fact.id}", title=fact.title, year=fact.year))
        if len(out) == TRACKS_PER_CARD:
            break
    return out


def _reason(model: ReadModel, catalog: Catalog, reason: dict[str, object]) -> fy.FeedReason:
    kind = fy.FeedReasonKind(str(reason.get("kind", "DISCOVER")))
    via = reason.get("via")
    via_artist = None
    genre = None
    if kind is fy.FeedReasonKind.GENRE:
        genre = _genre(catalog, str(via) if via else None)
    elif isinstance(via, str) and via in model.graph.nodes:
        via_artist = convert.artist_summary(model.graph, via)
    via_kind = reason.get("viaKind")
    return fy.FeedReason(
        kind=kind,
        via_artist=via_artist,
        via_kind=fy.SeedKind(str(via_kind)) if via_kind and via_artist else None,
        genre=genre,
        friends=int(reason.get("count", 0) or 0),  # type: ignore[call-overload]
    )


def _reason_payload(reason: Reason) -> dict[str, object]:
    return {
        "kind": reason.kind.value,
        "via": reason.via,
        "viaKind": reason.via_kind,
        "count": reason.count,
    }


def _card(
    model: ReadModel,
    index: BrowseIndex,
    catalog: Catalog,
    position: int,
    artist_id: str,
    reason: dict[str, object],
    *,
    exploratory: bool,
) -> fy.FeedItem:
    return fy.FeedItem(
        position=position,
        artist=convert.artist_summary(model.graph, artist_id),
        reason=_reason(model, catalog, reason),
        genre=_genre(catalog, catalog.primary_genre.get(artist_id)),
        tracks=_tracks(index, artist_id),
        exploratory=exploratory,
    )


def _unwanted_now(session: Session, user_id: str) -> set[str]:
    """Artists to drop from a stored feed as its pages are read."""
    out = set(users.blocked_artist_ids(session, user_id))
    out |= {f.artist_id for f in zr.follows(session, user_id)}
    for row in zr.feedback(session, user_id):
        if row.kind == "NOT_INTERESTED" and row.subject.startswith("artists/"):
            out.add(row.subject.removeprefix("artists/"))
    return out


def _page_token(feed_id: str, user_id: str, offset: int) -> str:
    return f"{feed_id}~{encode_token(offset, feed_id, user_id)}"


def _read_token(token: str, user_id: str) -> tuple[str, int]:
    feed_id, _, rest = token.partition("~")
    try:
        uuid.UUID(feed_id)
    except ValueError:
        raise invalid_argument("pageToken is not valid.", field="pageToken") from None
    return feed_id, decode_token(rest, feed_id, user_id)


def _make_feed(
    request: Request,
    session: Session,
    model: ReadModel,
    catalog: Catalog,
    signals: Signals,
    seed_key: str,
    arm: str,
) -> ZFeed:
    embeddings = embeddings_for(model, catalog, session)
    seed = int.from_bytes(hashlib.sha256(seed_key.encode()).digest()[:8], "big")
    return recommend(
        catalog,
        embeddings,
        signals,
        RANKERS.current(session),
        rng=random.Random(seed),  # noqa: S311 - reproducible ranking, not a secret
        arm=arm,
    )


@router.get(
    "/users/{user:rid}/feed",
    response_model=fy.Feed,
    summary="GetFeed",
    dependencies=Analyze,
)
def get_feed(
    user: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
    page_token: Annotated[str, Query(alias="pageToken", max_length=600)] = "",
) -> fy.Feed:
    """The listener's For You feed. Without a page token, a fresh feed is made."""
    user_id = authorize_user(user, who)
    _private(response)
    index = browse_index(model, session)
    catalog = catalog_view(model, index)
    now = datetime.now(UTC)

    if page_token:
        feed_id, offset = _read_token(page_token, user_id)
        stored = zr.get_feed(session, user_id, feed_id)
        if stored is None:
            raise not_found(f"users/{user_id}/feeds/{feed_id}", reason="FEED_NOT_FOUND")
        prefs = session.get(m.Preferences, user_id)
        personalize = prefs.personalize if prefs is not None else True
        cold, model_version, arm = stored.cold, stored.model_version, stored.arm
    else:
        signals, personalize = load_signals(session, user_id, now)
        settings = app_state(request).settings
        try:
            experiment = experiments.parse(settings.zstar_experiment)
        except ValueError:
            experiment = None
        arm = experiments.assign(user_id, experiment)
        feed_id = str(uuid.uuid4())
        made = _make_feed(request, session, model, catalog, signals, f"{user_id}:{feed_id}", arm)
        stored = m.FeedRequest(
            id=feed_id,
            user_id=user_id,
            created_at=now,
            catalog_version=catalog.version,
            model_version=made.model_version,
            arm=made.arm,
            candidates=made.candidates,
            cold=made.profile.cold,
        )
        zr.save_feed(
            session,
            stored,
            (
                m.FeedItem(
                    feed_id=feed_id,
                    position=i,
                    artist_id=item.artist_id,
                    value=item.value,
                    sources=list(item.sources),
                    reason=_reason_payload(item.reason),
                    features=dict(item.features),
                    heads=dict(item.heads),
                    exploratory=item.exploratory,
                )
                for i, item in enumerate(made.items)
            ),
        )
        offset = 0
        cold, model_version, arm = made.profile.cold, made.model_version, made.arm

    unwanted = _unwanted_now(session, user_id)
    items: list[fy.FeedItem] = []
    cursor = offset
    total = zr.feed_length(session, feed_id)
    while len(items) < page_size and cursor < total:
        batch = zr.feed_items(session, feed_id, cursor, page_size * 2)
        if not batch:
            break
        for row in batch:
            cursor = row.position + 1
            if row.artist_id in unwanted or row.artist_id not in model.graph.nodes:
                continue
            items.append(
                _card(
                    model,
                    index,
                    catalog,
                    row.position,
                    row.artist_id,
                    row.reason,
                    exploratory=row.exploratory,
                )
            )
            if len(items) == page_size:
                break
    return fy.Feed(
        name=f"users/{user_id}/feeds/{feed_id}",
        items=items,
        next_page_token=_page_token(feed_id, user_id, cursor) if cursor < total else "",
        cold=cold,
        personalized=personalize,
        model_version=model_version,
        arm=arm,
    )


@router.post(
    "/feed:preview",
    response_model=fy.Feed,
    summary="PreviewFeed",
    dependencies=Analyze,
)
def preview_feed(
    body: fy.PreviewFeedRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> fy.Feed:
    """A feed from artists the browser remembers, for signed-out visitors. Nothing is stored."""
    _private(response)
    index = browse_index(model, session)
    catalog = catalog_view(model, index)
    now = datetime.now(UTC)
    seeds = {
        a: now
        for a in (parse_name(s, "artists", field="seeds") for s in body.seeds)
        if a in model.graph.nodes
    }
    exclude = frozenset(parse_name(s, "artists", field="exclude") for s in body.exclude)
    signals = Signals(now=now, follows=seeds, blocked=frozenset(who.blocked) | exclude)
    day = now.date().isoformat()
    made = _make_feed(
        request, session, model, catalog, signals, f"preview:{sorted(seeds)}:{day}", "control"
    )
    items = [
        _card(
            model,
            index,
            catalog,
            i,
            item.artist_id,
            _reason_payload(item.reason),
            exploratory=item.exploratory,
        )
        for i, item in enumerate(made.items[: body.page_size])
    ]
    return fy.Feed(
        name="",
        items=items,
        cold=made.profile.cold,
        personalized=False,
        model_version=made.model_version,
        arm="control",
    )


# --- Events ------------------------------------------------------------------


def _event_time(value: str | None, now: datetime) -> datetime:
    if not value:
        return now
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return now
    if parsed.tzinfo is None:
        return now
    # A client clock far off is not trusted.
    return parsed if abs(parsed - now) <= CLOCK_SKEW else now


@router.post(
    "/users/{user:rid}/events:batchCreate",
    response_model=fy.BatchCreateEventsResponse,
    summary="BatchCreateEvents",
    dependencies=Write,
)
def batch_create_events(
    user: str,
    body: fy.BatchCreateEventsRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> fy.BatchCreateEventsResponse:
    """Stores interaction events (idempotent by event ID) when personalization is on."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    _private(response)
    prefs = session.get(m.Preferences, user_id)
    if prefs is not None and not prefs.personalize:
        return fy.BatchCreateEventsResponse(received=len(body.events), stored=0, personalize=False)
    now = datetime.now(UTC)
    accepted: list[zr.NewEvent] = []
    feed_prefix = f"users/{user_id}/feeds/"
    for event in body.events:
        artist_id = parse_name(event.artist, "artists", field="events.artist")
        if artist_id not in model.graph.nodes:
            continue
        feed_id = None
        if event.feed:
            if not event.feed.startswith(feed_prefix):
                raise invalid_argument(
                    "events.feed must be one of your feeds.", field="events.feed"
                )
            feed_id = event.feed.removeprefix(feed_prefix)
        accepted.append(
            zr.NewEvent(
                event_id=event.event_id,
                kind=event.kind.value,
                artist_id=artist_id,
                surface=event.surface.value,
                feed_id=feed_id,
                position=event.position,
                dwell_ms=event.dwell_ms,
                created_at=_event_time(event.time, now),
            )
        )
    stored = zr.record_events(session, user_id, accepted)
    return fy.BatchCreateEventsResponse(received=len(body.events), stored=stored, personalize=True)


@router.post(
    "/users/{user:rid}/personalization:reset",
    response_model=api.Empty,
    summary="ResetPersonalization",
    dependencies=Write,
)
def reset_personalization(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.Empty:
    """Forgets everything learned from activity (events and served feeds)."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    zr.forget_events(session, user_id)
    _audit(session, user_id, "personalization.reset")
    _private(response)
    return api.Empty()


# --- Follows -----------------------------------------------------------------


def _followed(model: ReadModel, user_id: str, row: m.ArtistFollow) -> fy.FollowedArtist:
    present = row.artist_id in model.graph.nodes
    return fy.FollowedArtist(
        name=f"users/{user_id}/followedArtists/{row.artist_id}",
        artist=convert.artist_summary(model.graph, row.artist_id) if present else None,
        create_time=_timestamp(row.created_at),
    )


@router.get(
    "/users/{user:rid}/followedArtists",
    response_model=fy.ListFollowedArtistsResponse,
    summary="ListFollowedArtists",
    dependencies=Read,
)
def list_followed_artists(
    user: str, response: Response, who: ViewerDep, session: SessionDep, model: ReadModelDep
) -> fy.ListFollowedArtistsResponse:
    """Followed artists, newest first."""
    user_id = authorize_user(user, who)
    rows = zr.follows(session, user_id)
    _private(response)
    return fy.ListFollowedArtistsResponse(
        followed_artists=[_followed(model, user_id, r) for r in rows], total_size=len(rows)
    )


@router.post(
    "/users/{user:rid}/followedArtists",
    response_model=fy.FollowedArtist,
    summary="CreateFollowedArtist",
    dependencies=Write,
)
def create_followed_artist(
    user: str,
    body: fy.CreateFollowedArtistRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> fy.FollowedArtist:
    """Follows an artist (idempotent: following again returns the existing follow)."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    artist_id = parse_name(body.artist, "artists", field="artist")
    if artist_id not in model.graph.nodes:
        raise not_found(f"artists/{artist_id}", reason="ARTIST_NOT_FOUND")
    now = datetime.now(UTC)
    if zr.add_follow(session, user_id, artist_id, now):
        # Following outranks an old "not interested".
        zr.remove_feedback(session, user_id, f"artists/{artist_id}", "NOT_INTERESTED")
        _audit(session, user_id, "follow.create")
    session.flush()
    row = session.get(m.ArtistFollow, (user_id, artist_id))
    _private(response)
    return (
        _followed(model, user_id, row)
        if row is not None
        else fy.FollowedArtist(
            name=f"users/{user_id}/followedArtists/{artist_id}", create_time=_timestamp(now)
        )
    )


@router.delete(
    "/users/{user:rid}/followedArtists/{artist:rid}",
    response_model=api.Empty,
    summary="DeleteFollowedArtist",
    dependencies=Write,
)
def delete_followed_artist(
    user: str,
    artist: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Unfollows an artist."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    artist_id = parse_name(artist, "artists", field="name")
    if not zr.remove_follow(session, user_id, artist_id):
        raise not_found(f"users/{user_id}/followedArtists/{artist_id}", reason="FOLLOW_NOT_FOUND")
    _audit(session, user_id, "follow.delete")
    _private(response)
    return api.Empty()


# --- Taste feedback ------------------------------------------------------------


def _feedback_id(kind: str, subject: str) -> str:
    collection, _, ident = subject.partition("/")
    return f"{kind}.{collection}.{ident}"


def _feedback(
    model: ReadModel, catalog: Catalog, user_id: str, row: m.TasteFeedback
) -> fy.TasteFeedback:
    collection, _, ident = row.subject.partition("/")
    artist = (
        convert.artist_summary(model.graph, ident)
        if collection == "artists" and ident in model.graph.nodes
        else None
    )
    genre = _genre(catalog, ident) if collection == "genres" else None
    return fy.TasteFeedback(
        name=f"users/{user_id}/tasteFeedback/{_feedback_id(row.kind, row.subject)}",
        kind=fy.TasteFeedbackKind(row.kind),
        artist=artist,
        genre=genre,
        create_time=_timestamp(row.created_at),
    )


@router.get(
    "/users/{user:rid}/tasteFeedback",
    response_model=fy.ListTasteFeedbackResponse,
    summary="ListTasteFeedback",
    dependencies=Read,
)
def list_taste_feedback(
    user: str, response: Response, who: ViewerDep, session: SessionDep, model: ReadModelDep
) -> fy.ListTasteFeedbackResponse:
    """Feedback given, newest first (to review and undo)."""
    user_id = authorize_user(user, who)
    catalog = catalog_view(model, browse_index(model, session))
    _private(response)
    return fy.ListTasteFeedbackResponse(
        taste_feedback=[
            _feedback(model, catalog, user_id, r) for r in zr.feedback(session, user_id)
        ]
    )


@router.post(
    "/users/{user:rid}/tasteFeedback",
    response_model=fy.TasteFeedback,
    summary="CreateTasteFeedback",
    dependencies=Write,
)
def create_taste_feedback(
    user: str,
    body: fy.CreateTasteFeedbackRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> fy.TasteFeedback:
    """Not interested in an artist, more like an artist, or less of a genre."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    catalog = catalog_view(model, browse_index(model, session))
    if body.kind is fy.TasteFeedbackKind.LESS_OF_GENRE:
        if not body.genre:
            raise invalid_argument("genre is required for LESS_OF_GENRE.", field="genre")
        genre_id = parse_name(body.genre, "genres", field="genre")
        if genre_id not in catalog.genre_names:
            raise not_found(f"genres/{genre_id}", reason="GENRE_NOT_FOUND")
        subject = f"genres/{genre_id}"
    else:
        if not body.artist:
            raise invalid_argument("artist is required.", field="artist")
        artist_id = parse_name(body.artist, "artists", field="artist")
        if artist_id not in model.graph.nodes:
            raise not_found(f"artists/{artist_id}", reason="ARTIST_NOT_FOUND")
        subject = f"artists/{artist_id}"
    row = zr.give_feedback(session, user_id, subject, body.kind.value, datetime.now(UTC))
    _audit(session, user_id, f"feedback.{body.kind.value.lower()}")
    _private(response)
    return _feedback(model, catalog, user_id, row)


@router.delete(
    "/users/{user:rid}/tasteFeedback/{feedback}",
    response_model=api.Empty,
    summary="DeleteTasteFeedback",
    dependencies=Write,
)
def delete_taste_feedback(
    user: str,
    feedback: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Withdraws feedback (undo)."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    parts = feedback.split(".", 2)
    if (
        len(parts) != 3  # noqa: PLR2004 - kind.collection.id
        or parts[0] not in zr.FEEDBACK_KINDS
        or parts[1] not in {"artists", "genres"}
    ):
        raise invalid_argument("Not a taste feedback name.", field="name")
    kind, collection, ident = parts
    if not zr.remove_feedback(session, user_id, f"{collection}/{ident}", kind):
        raise ApiError(Status.NOT_FOUND, "No such feedback.", reason="FEEDBACK_NOT_FOUND")
    _audit(session, user_id, "feedback.delete")
    _private(response)
    return api.Empty()


# --- Imports -------------------------------------------------------------------


@router.get(
    "/users/{user:rid}/listeningImport",
    response_model=fy.ListeningImport,
    summary="GetListeningImport",
    dependencies=Read,
)
def get_listening_import(
    user: str, response: Response, who: ViewerDep, session: SessionDep
) -> fy.ListeningImport:
    """How many imported artists are kept for For You."""
    user_id = authorize_user(user, who)
    _private(response)
    return fy.ListeningImport(
        name=f"users/{user_id}/listeningImport", artists=zr.imported_artists(session, user_id)
    )


@router.put(
    "/users/{user:rid}/listeningImport",
    response_model=fy.ListeningImport,
    summary="ReplaceListeningImport",
    dependencies=Write,
)
def replace_listening_import(
    user: str,
    body: fy.ImportListeningRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> fy.ListeningImport:
    """Keeps an import's artists and play counts for For You, at the listener's request.

    Nothing else from the file is sent or kept. Replaces any earlier import.
    """
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    counts: dict[str, int] = {}
    for entry in body.artists:
        artist_id = parse_name(entry.artist, "artists", field="artists.artist")
        if artist_id in model.graph.nodes:
            counts[artist_id] = counts.get(artist_id, 0) + entry.plays
    kept = zr.replace_import(session, user_id, counts, datetime.now(UTC))
    _audit(session, user_id, "import.replace")
    _private(response)
    return fy.ListeningImport(name=f"users/{user_id}/listeningImport", artists=kept)


@router.delete(
    "/users/{user:rid}/listeningImport",
    response_model=api.Empty,
    summary="DeleteListeningImport",
    dependencies=Write,
)
def delete_listening_import(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.Empty:
    """Forgets imported listening."""
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    zr.clear_import(session, user_id)
    _audit(session, user_id, "import.delete")
    _private(response)
    return api.Empty()
