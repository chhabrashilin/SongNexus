"""Development demo data (``songnexus seed-demo``): synthetic accounts and their removal.

Every account written here carries ``users.synthetic_source``; removal goes
through the same erase path as account deletion, so nothing synthetic is left
behind in any user table. See docs/synthetic-data.md.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from songnexus.storage import models as m
from songnexus.storage import user_repository as users

CHUNK = 500


def catalog_artist_genres(session: Session) -> list[tuple[str, int, dict[str, int]]]:
    """Returns (artist, public audience, genre name -> votes) for artists with a page."""
    audience = dict(
        session.execute(
            select(m.ArtistAudience.artist_id, func.max(m.ArtistAudience.listeners)).group_by(
                m.ArtistAudience.artist_id
            )
        ).all()
    )
    genres: dict[str, dict[str, int]] = defaultdict(dict)
    for artist_id, name, votes in session.execute(
        select(m.ArtistGenre.artist_id, m.Genre.name, func.sum(m.ArtistGenre.votes))
        .join(m.Genre, m.Genre.id == m.ArtistGenre.genre_id)
        .join(m.Artist, m.Artist.id == m.ArtistGenre.artist_id)
        .where(m.Artist.detail_level != "stub")
        .group_by(m.ArtistGenre.artist_id, m.Genre.name)
    ):
        genres[str(artist_id)][str(name)] = int(votes or 0)
    return sorted((a, int(audience.get(a, 0) or 0), g) for a, g in genres.items())


def recordings_by(session: Session, artist_ids: Iterable[str]) -> dict[str, str]:
    """Returns one recording each artist is the primary artist of (for demo shares)."""
    ids = list(artist_ids)
    found: dict[str, str] = {}
    if not ids:
        return found
    for artist_id, recording_id in session.execute(
        select(m.RecordingCredit.artist_id, func.min(m.RecordingCredit.recording_id))
        .where(m.RecordingCredit.artist_id.in_(ids), m.RecordingCredit.role == "primary")
        .group_by(m.RecordingCredit.artist_id)
    ):
        found[str(artist_id)] = str(recording_id)
    return found


def synthetic_user_ids(session: Session, source: str) -> list[str]:
    """Returns every account created by ``source``."""
    return list(session.scalars(select(m.User.id).where(m.User.synthetic_source == source)))


def find_by_identity(session: Session, firebase_uid: str) -> m.User | None:
    """Returns the live account with this sign-in identity, synthetic or not."""
    return users.find_user_by_firebase_uid(session, firebase_uid)


def add_user(
    session: Session, user_id: str, firebase_uid: str | None, source: str, now: datetime
) -> None:
    """Creates a synthetic account."""
    session.add(
        m.User(
            id=user_id,
            firebase_uid=firebase_uid,
            created_at=now,
            age_confirmed_at=now,
            synthetic_source=source,
        )
    )


def clear_content(session: Session, user_ids: list[str], now: datetime) -> None:
    """Erases everything the accounts own (as account deletion would), keeping the rows."""
    for user_id in user_ids:
        users.erase_user(session, user_id, now)


def remove_users(session: Session, user_ids: list[str], now: datetime) -> int:
    """Erases synthetic accounts and deletes their rows now (no 30-day wait: never real)."""
    clear_content(session, user_ids, now)
    for start in range(0, len(user_ids), CHUNK):
        chunk = user_ids[start : start + CHUNK]
        session.execute(delete(m.AuditEntry).where(m.AuditEntry.user_id.in_(chunk)))
        session.execute(delete(m.User).where(m.User.id.in_(chunk)))
    return len(user_ids)


def replace_tallies(
    session: Session, user_ids: list[str], rows: Iterable[m.ListeningTally]
) -> None:
    """Replaces the listening tallies of the given (synthetic) accounts."""
    for start in range(0, len(user_ids), CHUNK):
        chunk = user_ids[start : start + CHUNK]
        session.execute(delete(m.ListeningTally).where(m.ListeningTally.user_id.in_(chunk)))
    session.add_all(list(rows))
    session.flush()


def delete_demo_charts(session: Session, community_ids: Iterable[str] | None = None) -> int:
    """Deletes stored charts that synthetic members fed (``demo``).

    Charts are derived data: the chart job rebuilds any that still have members.

    Args:
        session: The open session.
        community_ids: Limit to these communities; ``None`` means every community.
    """
    query = select(m.CommunityChart)
    if community_ids is not None:
        ids = list(community_ids)
        if not ids:
            return 0
        query = query.where(m.CommunityChart.community_id.in_(ids))
    removed = 0
    for row in list(session.scalars(query)):
        if (row.payload or {}).get("demo"):
            session.delete(row)
            removed += 1
    session.flush()
    return removed
