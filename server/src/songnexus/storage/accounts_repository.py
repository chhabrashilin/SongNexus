"""Linked accounts, listening tallies and OAuth flows (ADR 0006)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from songnexus.storage import models as m


def get_account(session: Session, user_id: str, provider: str) -> m.LinkedAccount | None:
    """Returns one linked account, or None."""
    return session.get(m.LinkedAccount, (user_id, provider))


def list_accounts(session: Session, user_id: str) -> list[m.LinkedAccount]:
    """Returns a user's linked accounts, by provider."""
    return list(
        session.scalars(
            select(m.LinkedAccount)
            .where(m.LinkedAccount.user_id == user_id)
            .order_by(m.LinkedAccount.provider)
        )
    )


def due_accounts(session: Session, now: datetime, limit: int) -> list[m.LinkedAccount]:
    """Returns active accounts whose next sync is due, oldest first."""
    return list(
        session.scalars(
            select(m.LinkedAccount)
            .where(
                m.LinkedAccount.status == "ACTIVE",
                (m.LinkedAccount.next_sync_after.is_(None))
                | (m.LinkedAccount.next_sync_after <= now),
            )
            .order_by(m.LinkedAccount.next_sync_after, m.LinkedAccount.user_id)
            .limit(limit)
        )
    )


def unlink(session: Session, user_id: str, provider: str) -> bool:
    """Deletes a linked account, its token and every tally synced from it; True if it existed."""
    session.execute(
        delete(m.ListeningTally).where(
            m.ListeningTally.user_id == user_id, m.ListeningTally.provider == provider
        )
    )
    result = session.execute(
        delete(m.LinkedAccount).where(
            m.LinkedAccount.user_id == user_id, m.LinkedAccount.provider == provider
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def tallies(session: Session, user_id: str, provider: str) -> dict[str, m.ListeningTally]:
    """Returns artist ID -> tally for one linked account."""
    return {
        t.artist_id: t
        for t in session.scalars(
            select(m.ListeningTally).where(
                m.ListeningTally.user_id == user_id, m.ListeningTally.provider == provider
            )
        )
    }


def save_tallies(
    session: Session,
    user_id: str,
    provider: str,
    rows: Mapping[str, tuple[int, datetime | None]],
) -> None:
    """Writes artist ID -> (plays, last played) for one linked account (insert or replace)."""
    current = tallies(session, user_id, provider)
    for artist_id, (plays, last_played_at) in rows.items():
        row = current.get(artist_id)
        if row is None:
            session.add(
                m.ListeningTally(
                    user_id=user_id,
                    provider=provider,
                    artist_id=artist_id,
                    plays=plays,
                    last_played_at=last_played_at,
                )
            )
        else:
            row.plays = plays
            row.last_played_at = last_played_at


def listening(session: Session, user_id: str) -> list[m.ListeningTally]:
    """Returns every tally of a user, across providers."""
    return list(
        session.scalars(select(m.ListeningTally).where(m.ListeningTally.user_id == user_id))
    )


def add_flow(session: Session, flow: m.OAuthFlow) -> None:
    """Stores a linking flow."""
    session.add(flow)


def take_flow(session: Session, state_hash: str, now: datetime) -> m.OAuthFlow | None:
    """Removes and returns a live flow (single use); expired flows are removed and not returned."""
    flow = session.get(m.OAuthFlow, state_hash)
    if flow is None:
        return None
    session.delete(flow)
    expires_at = (
        flow.expires_at if flow.expires_at.tzinfo else flow.expires_at.replace(tzinfo=now.tzinfo)
    )
    return flow if expires_at > now else None


def purge_flows(session: Session, now: datetime) -> int:
    """Removes expired linking flows."""
    result = session.execute(delete(m.OAuthFlow).where(m.OAuthFlow.expires_at <= now))
    return int(result.rowcount)  # type: ignore[attr-defined]
