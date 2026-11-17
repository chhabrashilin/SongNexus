"""Around you: memberships, member tallies for aggregation, and cached charts.

Authorization happens in callers. Nothing here returns another listener's
identity to a caller outside aggregation: ``member_tallies`` replaces user IDs
with opaque integers before returning.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from songnexus.storage import models as m

SYNTHETIC_PROVIDER = "SYNTHETIC"


def memberships(session: Session, user_id: str) -> dict[str, m.CommunityMembership]:
    """Returns a user's memberships by kind (CAMPUS, CITY)."""
    return {
        row.kind: row
        for row in session.scalars(
            select(m.CommunityMembership).where(m.CommunityMembership.user_id == user_id)
        )
    }


def join(session: Session, user_id: str, kind: str, community_id: str, now: datetime) -> None:
    """Joins a community, replacing any membership of the same kind."""
    row = session.get(m.CommunityMembership, (user_id, kind))
    if row is None:
        session.add(
            m.CommunityMembership(
                user_id=user_id,
                kind=kind,
                community_id=community_id,
                joined_at=now,
                synthetic=False,
            )
        )
    elif row.community_id != community_id:
        row.community_id = community_id
        row.joined_at = now


def leave(session: Session, user_id: str, kind: str) -> bool:
    """Deletes a membership now. Returns False when there was none."""
    result = session.execute(
        delete(m.CommunityMembership).where(
            m.CommunityMembership.user_id == user_id, m.CommunityMembership.kind == kind
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def erase(session: Session, user_id: str) -> None:
    """Deletes every membership of a user (account deletion)."""
    session.execute(delete(m.CommunityMembership).where(m.CommunityMembership.user_id == user_id))


def has_listening(session: Session, user_id: str) -> bool:
    """True when the user has any listening tally (their own data, for their own view)."""
    found = session.scalars(
        select(m.ListeningTally.artist_id).where(m.ListeningTally.user_id == user_id).limit(1)
    ).first()
    return found is not None


def member_tallies(
    session: Session, community_id: str, *, include_synthetic: bool
) -> tuple[list[tuple[int, str, int, datetime | None]], bool]:
    """Returns every member's tallies as (opaque member, artist, plays, last played).

    Plays are summed across a member's linked services; the last play is the
    latest. Members of deleted accounts are excluded. The second value is True
    when synthetic (development) members contributed.
    """
    query = (
        select(
            m.CommunityMembership.user_id,
            m.CommunityMembership.synthetic,
            m.ListeningTally.artist_id,
            func.sum(m.ListeningTally.plays),
            func.max(m.ListeningTally.last_played_at),
        )
        .join(m.ListeningTally, m.ListeningTally.user_id == m.CommunityMembership.user_id)
        .join(m.User, m.User.id == m.CommunityMembership.user_id)
        .where(m.CommunityMembership.community_id == community_id, m.User.deleted_at.is_(None))
        .group_by(
            m.CommunityMembership.user_id,
            m.CommunityMembership.synthetic,
            m.ListeningTally.artist_id,
        )
    )
    if not include_synthetic:
        query = query.where(m.CommunityMembership.synthetic.is_(False))
    keys: dict[str, int] = {}
    rows: list[tuple[int, str, int, datetime | None]] = []
    synthetic = False
    for user_id, is_synthetic, artist_id, plays, last in session.execute(query):
        member = keys.setdefault(user_id, len(keys))
        synthetic = synthetic or bool(is_synthetic)
        rows.append((member, artist_id, int(plays or 0), last))
    return rows, synthetic


def communities_with_members(session: Session) -> list[str]:
    """Returns the IDs of every community with at least one member."""
    return list(
        session.scalars(
            select(m.CommunityMembership.community_id)
            .distinct()
            .order_by(m.CommunityMembership.community_id)
        )
    )


def charts(session: Session, community_id: str, since: datetime) -> list[m.CommunityChart]:
    """Returns stored charts computed at or after ``since``, newest first."""
    return list(
        session.scalars(
            select(m.CommunityChart)
            .where(
                m.CommunityChart.community_id == community_id,
                m.CommunityChart.computed_at >= since,
            )
            .order_by(m.CommunityChart.computed_at.desc())
        )
    )


def latest_chart(session: Session, community_id: str) -> m.CommunityChart | None:
    """Returns the newest stored chart, if any."""
    return session.scalars(
        select(m.CommunityChart)
        .where(m.CommunityChart.community_id == community_id)
        .order_by(m.CommunityChart.computed_at.desc())
        .limit(1)
    ).first()


def save_chart(
    session: Session, community_id: str, computed_at: datetime, payload: dict[str, Any]
) -> None:
    """Stores a chart; earlier charts from the same UTC day are replaced (one per day)."""
    day = computed_at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    session.execute(
        delete(m.CommunityChart).where(
            m.CommunityChart.community_id == community_id,
            m.CommunityChart.computed_at >= day,
            m.CommunityChart.computed_at < day + timedelta(days=1),
        )
        # Loaded rows may hold naive times (SQLite); don't evaluate the filter in Python.
        .execution_options(synchronize_session=False)
    )
    session.add(
        m.CommunityChart(community_id=community_id, computed_at=computed_at, payload=payload)
    )


def delete_charts(session: Session, community_ids: Iterable[str]) -> int:
    """Removes every stored chart of the given communities."""
    ids = list(community_ids)
    if not ids:
        return 0
    result = session.execute(delete(m.CommunityChart).where(m.CommunityChart.community_id.in_(ids)))
    return int(result.rowcount)  # type: ignore[attr-defined]


def purge_charts(session: Session, before: datetime) -> int:
    """Removes charts older than ``before`` (history is kept for 35 days)."""
    result = session.execute(delete(m.CommunityChart).where(m.CommunityChart.computed_at < before))
    return int(result.rowcount)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Development demo members (``songnexus seed-community``)
# ---------------------------------------------------------------------------


def add_synthetic_member(
    session: Session,
    kind: str,
    community_id: str,
    tallies: dict[str, tuple[int, datetime | None]],
    now: datetime,
) -> str:
    """Creates a synthetic account (no sign-in identity) with a membership and tallies."""
    user_id = str(uuid.uuid4())
    session.add(m.User(id=user_id, firebase_uid=None, created_at=now, age_confirmed_at=now))
    session.flush()
    session.add(
        m.CommunityMembership(
            user_id=user_id, kind=kind, community_id=community_id, joined_at=now, synthetic=True
        )
    )
    for artist_id, (plays, last) in tallies.items():
        session.add(
            m.ListeningTally(
                user_id=user_id,
                provider=SYNTHETIC_PROVIDER,
                artist_id=artist_id,
                plays=plays,
                last_played_at=last,
            )
        )
    return user_id


def remove_synthetic(session: Session, community_id: str | None = None) -> tuple[int, list[str]]:
    """Deletes synthetic members (of one community, or all) and their accounts.

    Returns the number removed and the communities they belonged to.
    """
    query = select(m.CommunityMembership.user_id, m.CommunityMembership.community_id).where(
        m.CommunityMembership.synthetic.is_(True)
    )
    if community_id is not None:
        query = query.where(m.CommunityMembership.community_id == community_id)
    found: dict[str, set[str]] = defaultdict(set)
    for user_id, cid in session.execute(query):
        found[user_id].add(cid)
    ids = list(found)
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        session.execute(delete(m.ListeningTally).where(m.ListeningTally.user_id.in_(chunk)))
        session.execute(
            delete(m.CommunityMembership).where(m.CommunityMembership.user_id.in_(chunk))
        )
        session.execute(delete(m.AuditEntry).where(m.AuditEntry.user_id.in_(chunk)))
        session.execute(delete(m.User).where(m.User.id.in_(chunk)))
    return len(ids), sorted({c for cids in found.values() for c in cids})


def catalog_artists_by_audience(session: Session, limit: int) -> list[tuple[str, int]]:
    """Returns catalog artists with a page of their own, most listened first (demo seeding).

    Uses the public ListenBrainz audience where known; artists without one get 0.
    """
    rows = session.execute(
        select(m.Artist.id, func.coalesce(func.max(m.ArtistAudience.listeners), 0))
        .outerjoin(m.ArtistAudience, m.ArtistAudience.artist_id == m.Artist.id)
        .where(m.Artist.detail_level != "stub")
        .group_by(m.Artist.id)
        .order_by(func.coalesce(func.max(m.ArtistAudience.listeners), 0).desc(), m.Artist.id)
        .limit(limit)
    )
    return [(str(a), int(n)) for a, n in rows]
