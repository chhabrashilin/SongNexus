"""Storage for For You and Z-star (ADR 0010): follows, feedback, events, feeds, artifacts.

Every read is scoped to one user except the training and artifact functions,
which the offline jobs use.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from songnexus.storage import models as m

IMPORT_PROVIDER = "IMPORT"
EVENT_KINDS = frozenset({"IMPRESSION", "OPEN", "LISTEN", "SKIP", "HIDE", "SHARE"})
FEEDBACK_KINDS = frozenset({"NOT_INTERESTED", "MORE_LIKE_THIS", "LESS_OF_GENRE"})
EVENT_RETENTION = timedelta(days=180)
FEED_RETENTION = timedelta(days=30)
FATIGUE_WINDOW = timedelta(days=14)


# --- Follows ---------------------------------------------------------------


def follows(session: Session, user_id: str) -> list[m.ArtistFollow]:
    """The user's followed artists, newest first."""
    return list(
        session.scalars(
            select(m.ArtistFollow)
            .where(m.ArtistFollow.user_id == user_id)
            .order_by(m.ArtistFollow.created_at.desc(), m.ArtistFollow.artist_id)
        )
    )


def add_follow(session: Session, user_id: str, artist_id: str, now: datetime) -> bool:
    """Follows an artist. Returns False when already followed."""
    if session.get(m.ArtistFollow, (user_id, artist_id)) is not None:
        return False
    session.add(m.ArtistFollow(user_id=user_id, artist_id=artist_id, created_at=now))
    return True


def remove_follow(session: Session, user_id: str, artist_id: str) -> bool:
    """Unfollows an artist. Returns False when it was not followed."""
    result = session.execute(
        delete(m.ArtistFollow).where(
            m.ArtistFollow.user_id == user_id, m.ArtistFollow.artist_id == artist_id
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


# --- Feedback --------------------------------------------------------------


def feedback(session: Session, user_id: str) -> list[m.TasteFeedback]:
    """The user's taste feedback, newest first."""
    return list(
        session.scalars(
            select(m.TasteFeedback)
            .where(m.TasteFeedback.user_id == user_id)
            .order_by(m.TasteFeedback.created_at.desc(), m.TasteFeedback.subject)
        )
    )


def give_feedback(
    session: Session, user_id: str, subject: str, kind: str, now: datetime
) -> m.TasteFeedback:
    """Records feedback, refreshing its time when given again.

    "Not interested" and "more like this" on the same artist cancel each other:
    the newer one replaces the older.
    """
    opposite = {"NOT_INTERESTED": "MORE_LIKE_THIS", "MORE_LIKE_THIS": "NOT_INTERESTED"}.get(kind)
    if opposite is not None:
        session.execute(
            delete(m.TasteFeedback).where(
                m.TasteFeedback.user_id == user_id,
                m.TasteFeedback.subject == subject,
                m.TasteFeedback.kind == opposite,
            )
        )
    row = session.get(m.TasteFeedback, (user_id, subject, kind))
    if row is None:
        row = m.TasteFeedback(user_id=user_id, subject=subject, kind=kind, created_at=now)
        session.add(row)
    else:
        row.created_at = now
    return row


def remove_feedback(session: Session, user_id: str, subject: str, kind: str) -> bool:
    """Withdraws feedback (undo). Returns False when there was none."""
    result = session.execute(
        delete(m.TasteFeedback).where(
            m.TasteFeedback.user_id == user_id,
            m.TasteFeedback.subject == subject,
            m.TasteFeedback.kind == kind,
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


# --- Events ----------------------------------------------------------------


@dataclass(frozen=True)
class NewEvent:
    """An event as received from a client (already validated)."""

    event_id: str
    kind: str
    artist_id: str
    surface: str
    feed_id: str | None
    position: int | None
    dwell_ms: int | None
    created_at: datetime


def record_events(session: Session, user_id: str, events: Sequence[NewEvent]) -> int:
    """Stores events not seen before (by event ID); returns how many were new."""
    if not events:
        return 0
    ids = [e.event_id for e in events]
    known = set(
        session.scalars(
            select(m.InteractionEvent.event_id).where(
                m.InteractionEvent.user_id == user_id, m.InteractionEvent.event_id.in_(ids)
            )
        )
    )
    added = 0
    for e in events:
        if e.event_id in known:
            continue
        known.add(e.event_id)
        session.add(
            m.InteractionEvent(
                user_id=user_id,
                event_id=e.event_id,
                kind=e.kind,
                artist_id=e.artist_id,
                surface=e.surface,
                feed_id=e.feed_id,
                position=e.position,
                dwell_ms=e.dwell_ms,
                created_at=e.created_at,
            )
        )
        added += 1
    return added


@dataclass(frozen=True)
class EngagementRow:
    """Aggregated activity with one artist."""

    impressions: int
    opens: int
    listens: int
    skips: int
    dwell_ms: int
    last_at: datetime | None
    recent_impressions: int


def engagement(session: Session, user_id: str, now: datetime) -> dict[str, EngagementRow]:
    """Per-artist activity in the retention window (one grouped query)."""
    since = now - EVENT_RETENTION
    fatigue_since = now - FATIGUE_WINDOW
    counts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": defaultdict(int), "dwell": 0, "last": None, "recent": 0}
    )
    rows = session.execute(
        select(
            m.InteractionEvent.artist_id,
            m.InteractionEvent.kind,
            func.count(),
            func.coalesce(func.sum(m.InteractionEvent.dwell_ms), 0),
            func.max(m.InteractionEvent.created_at),
        )
        .where(m.InteractionEvent.user_id == user_id, m.InteractionEvent.created_at >= since)
        .group_by(m.InteractionEvent.artist_id, m.InteractionEvent.kind)
    )
    for artist_id, kind, n, dwell, last in rows:
        entry = counts[artist_id]
        entry["n"][kind] += int(n)
        entry["dwell"] += int(dwell or 0)
        if last is not None and (entry["last"] is None or last > entry["last"]):
            entry["last"] = last
    recent = session.execute(
        select(m.InteractionEvent.artist_id, func.count())
        .where(
            m.InteractionEvent.user_id == user_id,
            m.InteractionEvent.kind == "IMPRESSION",
            m.InteractionEvent.created_at >= fatigue_since,
        )
        .group_by(m.InteractionEvent.artist_id)
    )
    for artist_id, n in recent:
        counts[artist_id]["recent"] = int(n)
    return {
        a: EngagementRow(
            impressions=c["n"]["IMPRESSION"],
            opens=c["n"]["OPEN"],
            listens=c["n"]["LISTEN"],
            skips=c["n"]["SKIP"],
            dwell_ms=c["dwell"],
            last_at=c["last"],
            recent_impressions=c["recent"],
        )
        for a, c in counts.items()
    }


def event_count(session: Session, user_id: str) -> int:
    """How many events are stored for the user."""
    return int(
        session.scalar(select(func.count()).where(m.InteractionEvent.user_id == user_id)) or 0
    )


def recent_events(session: Session, user_id: str, limit: int) -> list[m.InteractionEvent]:
    """The user's newest events (for export)."""
    return list(
        session.scalars(
            select(m.InteractionEvent)
            .where(m.InteractionEvent.user_id == user_id)
            .order_by(m.InteractionEvent.created_at.desc())
            .limit(limit)
        )
    )


def forget_events(session: Session, user_id: str) -> int:
    """Deletes all of a user's events and served feeds (personalization reset)."""
    events = session.execute(
        delete(m.InteractionEvent).where(m.InteractionEvent.user_id == user_id)
    )
    session.execute(delete(m.FeedRequest).where(m.FeedRequest.user_id == user_id))
    return int(events.rowcount or 0)  # type: ignore[attr-defined]


# --- Listening (linked services and opted-in imports) ------------------------


def plays(session: Session, user_id: str) -> dict[str, tuple[int, datetime | None]]:
    """Artist -> (plays summed over providers, most recent play)."""
    out: dict[str, tuple[int, datetime | None]] = {}
    rows = session.execute(
        select(
            m.ListeningTally.artist_id,
            func.sum(m.ListeningTally.plays),
            func.max(m.ListeningTally.last_played_at),
        )
        .where(m.ListeningTally.user_id == user_id)
        .group_by(m.ListeningTally.artist_id)
    )
    for artist_id, total, last in rows:
        out[artist_id] = (int(total or 0), last)
    return out


def replace_import(session: Session, user_id: str, counts: Mapping[str, int], now: datetime) -> int:
    """Replaces the user's imported listening with ``counts``; returns artists stored."""
    session.execute(
        delete(m.ListeningTally).where(
            m.ListeningTally.user_id == user_id, m.ListeningTally.provider == IMPORT_PROVIDER
        )
    )
    for artist_id, n in counts.items():
        session.add(
            m.ListeningTally(
                user_id=user_id,
                provider=IMPORT_PROVIDER,
                artist_id=artist_id,
                plays=max(int(n), 1),
                last_played_at=now,
            )
        )
    return len(counts)


def imported_artists(session: Session, user_id: str) -> int:
    """How many artists the user's import holds."""
    return int(
        session.scalar(
            select(func.count()).where(
                m.ListeningTally.user_id == user_id,
                m.ListeningTally.provider == IMPORT_PROVIDER,
            )
        )
        or 0
    )


def clear_import(session: Session, user_id: str) -> int:
    """Deletes the user's imported listening; returns rows removed."""
    result = session.execute(
        delete(m.ListeningTally).where(
            m.ListeningTally.user_id == user_id, m.ListeningTally.provider == IMPORT_PROVIDER
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --- Friends ---------------------------------------------------------------


def friends_top_artists(session: Session, user_id: str) -> dict[str, int]:
    """Artist -> how many of the user's friends list it in a Top 5 they chose to share."""
    friend_ids = list(
        session.scalars(select(m.Friendship.friend_id).where(m.Friendship.user_id == user_id))
    )
    if not friend_ids:
        return {}
    sharing = set(
        session.scalars(
            select(m.SocialProfile.user_id).where(
                m.SocialProfile.user_id.in_(friend_ids),
                m.SocialProfile.share_top_artists.is_(True),
            )
        )
    )
    counts: dict[str, int] = defaultdict(int)
    for profile in session.scalars(select(m.Profile).where(m.Profile.user_id.in_(sharing))):
        for artist_id in profile.top_artist_ids:
            counts[artist_id] += 1
    return dict(counts)


# --- Feeds -----------------------------------------------------------------


def save_feed(session: Session, request: m.FeedRequest, items: Iterable[m.FeedItem]) -> None:
    """Stores a served feed and its items."""
    session.add(request)
    session.flush()
    session.add_all(list(items))


def get_feed(session: Session, user_id: str, feed_id: str) -> m.FeedRequest | None:
    """A served feed, only if it belongs to the user."""
    feed = session.get(m.FeedRequest, feed_id)
    return feed if feed is not None and feed.user_id == user_id else None


def feed_items(session: Session, feed_id: str, offset: int, limit: int) -> list[m.FeedItem]:
    """A page of a served feed, in order."""
    return list(
        session.scalars(
            select(m.FeedItem)
            .where(m.FeedItem.feed_id == feed_id, m.FeedItem.position >= offset)
            .order_by(m.FeedItem.position)
            .limit(limit)
        )
    )


def feed_length(session: Session, feed_id: str) -> int:
    """How many items a served feed holds."""
    return int(session.scalar(select(func.count()).where(m.FeedItem.feed_id == feed_id)) or 0)


# --- Training data -----------------------------------------------------------


@dataclass(frozen=True)
class LoggedImpression:
    """A served card the listener saw, with what happened next."""

    created_at: datetime
    features: Mapping[str, float]
    opened: bool
    listened: bool
    negative: bool


def logged_impressions(session: Session, since: datetime) -> list[LoggedImpression]:
    """Every seen feed card since ``since``, oldest first, labeled from its events.

    A card counts as seen when an IMPRESSION event names its feed and artist;
    cards that were served but never scrolled to are not examples.
    """
    outcomes: dict[tuple[str, str], set[str]] = defaultdict(set)
    rows = session.execute(
        select(
            m.InteractionEvent.feed_id, m.InteractionEvent.artist_id, m.InteractionEvent.kind
        ).where(m.InteractionEvent.feed_id.is_not(None), m.InteractionEvent.created_at >= since)
    )
    for feed_id, artist_id, kind in rows:
        if feed_id is not None:
            outcomes[(feed_id, artist_id)].add(kind)
    examples = []
    items = session.execute(
        select(
            m.FeedRequest.created_at, m.FeedItem.feed_id, m.FeedItem.artist_id, m.FeedItem.features
        )
        .join(m.FeedRequest, m.FeedRequest.id == m.FeedItem.feed_id)
        .where(m.FeedRequest.created_at >= since)
        .order_by(m.FeedRequest.created_at, m.FeedItem.position)
    )
    for created_at, feed_id, artist_id, features in items:
        kinds = outcomes.get((feed_id, artist_id))
        if not kinds or "IMPRESSION" not in kinds:
            continue
        examples.append(
            LoggedImpression(
                created_at=created_at,
                features=features,
                opened=bool(kinds & {"OPEN", "LISTEN"}),
                listened="LISTEN" in kinds,
                negative=bool(kinds & {"HIDE", "SKIP"}),
            )
        )
    return examples


def arm_outcomes(session: Session, since: datetime) -> dict[str, dict[str, int]]:
    """Per experiment arm: feeds served, cards seen, opens, listens, hides (A/B readout)."""
    arms: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    feeds = dict(
        session.execute(
            select(m.FeedRequest.id, m.FeedRequest.arm).where(m.FeedRequest.created_at >= since)
        ).all()
    )
    for arm in feeds.values():
        arms[arm]["feeds"] += 1
    rows = session.execute(
        select(m.InteractionEvent.feed_id, m.InteractionEvent.kind, func.count())
        .where(m.InteractionEvent.feed_id.in_(list(feeds)))
        .group_by(m.InteractionEvent.feed_id, m.InteractionEvent.kind)
    )
    for feed_id, kind, n in rows:
        if feed_id in feeds:
            arms[feeds[feed_id]][kind.lower()] += int(n)
    return {a: dict(v) for a, v in arms.items()}


# --- Artifacts ---------------------------------------------------------------


def put_artifact(
    session: Session,
    kind: str,
    version: str,
    *,
    payload: dict[str, Any],
    metrics: dict[str, Any],
    now: datetime,
) -> m.ZstarArtifact:
    """Stores (or replaces) an artifact, inactive."""
    key = f"{kind}:{version}"
    row = session.get(m.ZstarArtifact, key)
    if row is None:
        row = m.ZstarArtifact(id=key, kind=kind, version=version, active=False, created_at=now)
        session.add(row)
    row.payload = payload
    row.metrics = metrics
    row.created_at = now
    return row


def activate(session: Session, kind: str, version: str) -> None:
    """Makes one artifact of a kind the active one."""
    session.execute(
        update(m.ZstarArtifact).where(m.ZstarArtifact.kind == kind).values(active=False)
    )
    session.execute(
        update(m.ZstarArtifact).where(m.ZstarArtifact.id == f"{kind}:{version}").values(active=True)
    )


def active_artifact(session: Session, kind: str) -> m.ZstarArtifact | None:
    """The active artifact of a kind, if any."""
    return session.scalars(
        select(m.ZstarArtifact).where(m.ZstarArtifact.kind == kind, m.ZstarArtifact.active)
    ).first()


def active_version(session: Session, kind: str) -> str | None:
    """Only the version of the active artifact (cheap, for cache checks)."""
    return session.scalar(
        select(m.ZstarArtifact.version).where(m.ZstarArtifact.kind == kind, m.ZstarArtifact.active)
    )


def artifact(session: Session, kind: str, version: str) -> m.ZstarArtifact | None:
    """An artifact by kind and version."""
    return session.get(m.ZstarArtifact, f"{kind}:{version}")


# --- Retention ---------------------------------------------------------------


def purge(session: Session, now: datetime) -> tuple[int, int]:
    """Deletes events past retention and served feeds past theirs; returns both counts."""
    events = session.execute(
        delete(m.InteractionEvent).where(m.InteractionEvent.created_at < now - EVENT_RETENTION)
    )
    feeds = session.execute(
        delete(m.FeedRequest).where(m.FeedRequest.created_at < now - FEED_RETENTION)
    )
    return (
        int(events.rowcount or 0),  # type: ignore[attr-defined]
        int(feeds.rowcount or 0),  # type: ignore[attr-defined]
    )
