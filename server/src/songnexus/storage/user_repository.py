"""Queries over user data. Authorization happens in callers; this module trusts its inputs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from songnexus.storage import models as m


def find_user_by_firebase_uid(session: Session, firebase_uid: str) -> m.User | None:
    """Returns the live account for a Firebase UID, if any."""
    return session.scalars(
        select(m.User).where(m.User.firebase_uid == firebase_uid, m.User.deleted_at.is_(None))
    ).first()


def get_live_user(session: Session, user_id: str) -> m.User | None:
    """Returns a user that has not been deleted."""
    return session.scalars(
        select(m.User).where(m.User.id == user_id, m.User.deleted_at.is_(None))
    ).first()


def create_user(session: Session, firebase_uid: str, now: datetime) -> m.User:
    """Creates an account with a random, opaque ID (never the Firebase UID)."""
    user = m.User(
        id=str(uuid.uuid4()), firebase_uid=firebase_uid, created_at=now, age_confirmed_at=now
    )
    session.add(user)
    session.flush()
    return user


def add_session(
    session: Session, token_hash: str, user_id: str, now: datetime, ttl: timedelta
) -> None:
    """Stores a new session by its token hash."""
    session.add(
        m.UserSession(
            token_hash=token_hash,
            user_id=user_id,
            created_at=now,
            expires_at=now + ttl,
            last_seen_at=now,
        )
    )


def find_session(session: Session, token_hash: str, now: datetime) -> m.UserSession | None:
    """Returns an unexpired session of a live user."""
    return session.scalars(
        select(m.UserSession)
        .join(m.User, m.User.id == m.UserSession.user_id)
        .where(
            m.UserSession.token_hash == token_hash,
            m.UserSession.expires_at > now,
            m.User.deleted_at.is_(None),
        )
    ).first()


def touch_session(session: Session, token_hash: str, now: datetime) -> None:
    """Records activity on a session."""
    session.execute(
        update(m.UserSession).where(m.UserSession.token_hash == token_hash).values(last_seen_at=now)
    )


def delete_session(session: Session, token_hash: str) -> None:
    """Signs one browser out."""
    session.execute(delete(m.UserSession).where(m.UserSession.token_hash == token_hash))


def delete_user_sessions(session: Session, user_id: str) -> int:
    """Signs a user out everywhere. Returns the number of sessions removed."""
    result = session.execute(delete(m.UserSession).where(m.UserSession.user_id == user_id))
    return int(result.rowcount)  # type: ignore[attr-defined]


def blocked_artist_ids(session: Session, user_id: str) -> list[str]:
    """Returns a user's blocked artists, oldest block first."""
    return list(
        session.scalars(
            select(m.BlockedArtist.artist_id)
            .where(m.BlockedArtist.user_id == user_id)
            .order_by(m.BlockedArtist.created_at, m.BlockedArtist.artist_id)
        )
    )


def add_block(session: Session, user_id: str, artist_id: str, now: datetime) -> bool:
    """Blocks an artist. Returns False when it was already blocked."""
    exists = session.get(m.BlockedArtist, (user_id, artist_id))
    if exists is not None:
        return False
    session.add(m.BlockedArtist(user_id=user_id, artist_id=artist_id, created_at=now))
    return True


def remove_block(session: Session, user_id: str, artist_id: str) -> bool:
    """Unblocks an artist. Returns False when it was not blocked."""
    result = session.execute(
        delete(m.BlockedArtist).where(
            m.BlockedArtist.user_id == user_id, m.BlockedArtist.artist_id == artist_id
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def audit(
    session: Session, user_id: str, action: str, request_id: str | None, now: datetime
) -> None:
    """Appends an audit entry."""
    session.add(m.AuditEntry(user_id=user_id, action=action, request_id=request_id, created_at=now))


def erase_user(session: Session, user_id: str, now: datetime) -> None:
    """Deletes a user's personal data now and marks the account for purge.

    Preferences, blocks, profile and sessions are removed immediately. The user
    row stays (without its Firebase UID) until the purge job removes it, so the
    deletion itself remains auditable for 30 days.
    """
    for model in (m.Preferences, m.BlockedArtist, m.Profile, m.UserSession):
        session.execute(delete(model).where(model.user_id == user_id))
    session.execute(
        update(m.User).where(m.User.id == user_id).values(deleted_at=now, firebase_uid=None)
    )


def purge_deleted_users(session: Session, deleted_before: datetime) -> int:
    """Removes accounts deleted before a cutoff, with everything that cascades."""
    ids = list(
        session.scalars(
            select(m.User.id).where(
                m.User.deleted_at.is_not(None), m.User.deleted_at < deleted_before
            )
        )
    )
    if ids:
        session.execute(delete(m.AuditEntry).where(m.AuditEntry.user_id.in_(ids)))
        session.execute(delete(m.User).where(m.User.id.in_(ids)))
    return len(ids)


def purge_expired_sessions(session: Session, now: datetime) -> int:
    """Removes expired sessions."""
    result = session.execute(delete(m.UserSession).where(m.UserSession.expires_at <= now))
    return int(result.rowcount)  # type: ignore[attr-defined]
