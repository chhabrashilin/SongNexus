"""Queries over friends and sharing (R2-7). Authorization happens in callers.

Friendships are stored as two rows (one per direction) so "my friends" is one
indexed lookup. A block hides both people from each other, so most reads take
the set of people either side blocked and leave them out.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from songnexus.storage import models as m

# ---------------------------------------------------------------------------
# Display names
# ---------------------------------------------------------------------------


def display_name(session: Session, user_id: str) -> str | None:
    """Returns the user's display name, or None if they haven't picked one."""
    row = session.get(m.SocialProfile, user_id)
    return None if row is None else row.display_name


def display_names(session: Session, user_ids: list[str]) -> dict[str, str]:
    """Returns display names for many users (missing ones are left out)."""
    if not user_ids:
        return {}
    rows = session.scalars(select(m.SocialProfile).where(m.SocialProfile.user_id.in_(user_ids)))
    return {r.user_id: r.display_name for r in rows}


def set_display_name(session: Session, user_id: str, name: str, now: datetime) -> m.SocialProfile:
    """Creates or updates the user's display name."""
    row = session.get(m.SocialProfile, user_id) or m.SocialProfile(user_id=user_id)
    row.display_name = name
    row.update_time = now
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def active_invites(session: Session, user_id: str, now: datetime) -> list[m.FriendInvite]:
    """Unexpired invites a user created, newest first."""
    return list(
        session.scalars(
            select(m.FriendInvite)
            .where(m.FriendInvite.user_id == user_id, m.FriendInvite.expires_at > now)
            .order_by(m.FriendInvite.created_at.desc(), m.FriendInvite.id)
        )
    )


def invites_created_since(session: Session, user_id: str, since: datetime) -> int:
    """How many invites a user created after ``since`` (for the daily limit)."""
    return (
        session.scalar(
            select(func.count())
            .select_from(m.FriendInvite)
            .where(m.FriendInvite.user_id == user_id, m.FriendInvite.created_at > since)
        )
        or 0
    )


def add_invite(
    session: Session, user_id: str, code_hash: str, now: datetime, expires: datetime
) -> m.FriendInvite:
    """Stores a new invite (its code is hashed by the caller)."""
    row = m.FriendInvite(
        id=str(uuid.uuid4()),
        code_hash=code_hash,
        user_id=user_id,
        created_at=now,
        expires_at=expires,
    )
    session.add(row)
    session.flush()
    return row


def find_invite(session: Session, code_hash: str, now: datetime) -> m.FriendInvite | None:
    """Returns the unexpired invite with this code hash, if any."""
    return session.scalars(
        select(m.FriendInvite).where(
            m.FriendInvite.code_hash == code_hash, m.FriendInvite.expires_at > now
        )
    ).first()


def delete_invite(session: Session, user_id: str, invite_id: str) -> bool:
    """Revokes one of the user's invites."""
    result = session.execute(
        delete(m.FriendInvite).where(
            m.FriendInvite.user_id == user_id, m.FriendInvite.id == invite_id
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def purge_invites(session: Session, now: datetime) -> int:
    """Removes expired invites."""
    result = session.execute(delete(m.FriendInvite).where(m.FriendInvite.expires_at <= now))
    return int(result.rowcount)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Friendships and blocks
# ---------------------------------------------------------------------------


def friends(session: Session, user_id: str) -> list[m.Friendship]:
    """The user's friendships, oldest first."""
    return list(
        session.scalars(
            select(m.Friendship)
            .where(m.Friendship.user_id == user_id)
            .order_by(m.Friendship.created_at, m.Friendship.friend_id)
        )
    )


def friend_count(session: Session, user_id: str) -> int:
    """How many friends a user has."""
    return (
        session.scalar(
            select(func.count()).select_from(m.Friendship).where(m.Friendship.user_id == user_id)
        )
        or 0
    )


def are_friends(session: Session, user_id: str, other_id: str) -> bool:
    """Whether two users are friends."""
    return session.get(m.Friendship, (user_id, other_id)) is not None


def befriend(session: Session, user_id: str, other_id: str, now: datetime) -> None:
    """Makes two users friends (both directions)."""
    session.add(m.Friendship(user_id=user_id, friend_id=other_id, created_at=now))
    session.add(m.Friendship(user_id=other_id, friend_id=user_id, created_at=now))
    session.flush()


def unfriend(session: Session, user_id: str, other_id: str) -> bool:
    """Ends a friendship (both directions). Returns False if there was none."""
    result = session.execute(
        delete(m.Friendship).where(
            or_(
                (m.Friendship.user_id == user_id) & (m.Friendship.friend_id == other_id),
                (m.Friendship.user_id == other_id) & (m.Friendship.friend_id == user_id),
            )
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def blocked_either_way(session: Session, user_id: str) -> set[str]:
    """Everyone the user blocked or who blocked the user."""
    mine = session.scalars(
        select(m.UserBlock.blocked_user_id).where(m.UserBlock.user_id == user_id)
    )
    theirs = session.scalars(
        select(m.UserBlock.user_id).where(m.UserBlock.blocked_user_id == user_id)
    )
    return set(mine) | set(theirs)


def is_blocked_either_way(session: Session, user_id: str, other_id: str) -> bool:
    """Whether either user blocked the other."""
    return (
        session.get(m.UserBlock, (user_id, other_id)) is not None
        or session.get(m.UserBlock, (other_id, user_id)) is not None
    )


def blocks(session: Session, user_id: str) -> list[m.UserBlock]:
    """People the user blocked, oldest first."""
    return list(
        session.scalars(
            select(m.UserBlock)
            .where(m.UserBlock.user_id == user_id)
            .order_by(m.UserBlock.created_at, m.UserBlock.blocked_user_id)
        )
    )


def block(session: Session, user_id: str, other_id: str, now: datetime) -> bool:
    """Blocks someone: ends the friendship and removes shares between them both ways.

    Returns False if they were already blocked.
    """
    if session.get(m.UserBlock, (user_id, other_id)) is not None:
        return False
    session.add(m.UserBlock(user_id=user_id, blocked_user_id=other_id, created_at=now))
    unfriend(session, user_id, other_id)
    session.execute(
        delete(m.Share).where(
            or_(
                (m.Share.sender_id == user_id) & (m.Share.recipient_id == other_id),
                (m.Share.sender_id == other_id) & (m.Share.recipient_id == user_id),
            )
        )
    )
    session.flush()
    return True


def unblock(session: Session, user_id: str, other_id: str) -> bool:
    """Removes a block. The friendship is not restored."""
    result = session.execute(
        delete(m.UserBlock).where(
            m.UserBlock.user_id == user_id, m.UserBlock.blocked_user_id == other_id
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def has_contact(session: Session, user_id: str, other_id: str) -> bool:
    """Whether the user knows ``other_id``: a friend now, or someone who shared with them."""
    if are_friends(session, user_id, other_id):
        return True
    return (
        session.scalar(
            select(func.count())
            .select_from(m.Share)
            .where(m.Share.recipient_id == user_id, m.Share.sender_id == other_id)
        )
        or 0
    ) > 0


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------


def shares_sent_since(session: Session, user_id: str, since: datetime) -> int:
    """How many shares a user sent after ``since`` (for the send limits)."""
    return (
        session.scalar(
            select(func.count())
            .select_from(m.Share)
            .where(m.Share.sender_id == user_id, m.Share.created_at > since)
        )
        or 0
    )


def add_share(
    session: Session,
    *,
    sender_id: str,
    recipient_id: str,
    kind: str,
    subjects: list[str],
    note: str,
    now: datetime,
) -> m.Share:
    """Stores a share."""
    row = m.Share(
        id=str(uuid.uuid4()),
        sender_id=sender_id,
        recipient_id=recipient_id,
        kind=kind,
        subjects=subjects,
        note=note,
        created_at=now,
        read_at=None,
    )
    session.add(row)
    session.flush()
    return row


def inbox(session: Session, user_id: str) -> list[m.Share]:
    """Shares the user received, newest first, without anyone blocked either way."""
    hidden = blocked_either_way(session, user_id)
    query = select(m.Share).where(m.Share.recipient_id == user_id)
    if hidden:
        query = query.where(m.Share.sender_id.not_in(hidden))
    return list(session.scalars(query.order_by(m.Share.created_at.desc(), m.Share.id)))


def get_share(session: Session, share_id: str) -> m.Share | None:
    """Returns a share by ID."""
    return session.get(m.Share, share_id)


def mark_read(session: Session, share: m.Share, now: datetime) -> None:
    """Marks one share read (keeps the first read time)."""
    if share.read_at is None:
        share.read_at = now
        session.flush()


def mark_all_read(session: Session, user_id: str, now: datetime) -> int:
    """Marks every unread share in the user's inbox read."""
    result = session.execute(
        update(m.Share)
        .where(m.Share.recipient_id == user_id, m.Share.read_at.is_(None))
        .values(read_at=now)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def delete_share(session: Session, share: m.Share) -> None:
    """Removes a share (from the recipient's inbox, and from the sender's sent list)."""
    session.delete(share)
    session.flush()


def sent(session: Session, user_id: str) -> list[m.Share]:
    """Shares the user sent, newest first (for export)."""
    return list(
        session.scalars(
            select(m.Share)
            .where(m.Share.sender_id == user_id)
            .order_by(m.Share.created_at.desc(), m.Share.id)
        )
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def add_report(session: Session, report: m.AbuseReport) -> m.AbuseReport:
    """Stores a report for moderators."""
    report.id = report.id or str(uuid.uuid4())
    session.add(report)
    session.flush()
    return report


def reports_by(session: Session, user_id: str) -> list[m.AbuseReport]:
    """Reports the user filed, oldest first (for export)."""
    return list(
        session.scalars(
            select(m.AbuseReport)
            .where(m.AbuseReport.reporter_id == user_id)
            .order_by(m.AbuseReport.created_at, m.AbuseReport.id)
        )
    )


def purge_reports(session: Session, created_before: datetime) -> int:
    """Removes reports older than the retention period."""
    result = session.execute(delete(m.AbuseReport).where(m.AbuseReport.created_at < created_before))
    return int(result.rowcount)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------


def erase(session: Session, user_id: str) -> None:
    """Removes the user's social data now: name, invites, friendships, blocks, shares.

    Shares the user sent disappear from friends' inboxes. Reports the user filed
    are removed; reports about the user lose the link to them (SET NULL on purge,
    cleared here so nothing points at a deleted account).
    """
    session.execute(delete(m.SocialProfile).where(m.SocialProfile.user_id == user_id))
    session.execute(delete(m.FriendInvite).where(m.FriendInvite.user_id == user_id))
    session.execute(
        delete(m.Friendship).where(
            or_(m.Friendship.user_id == user_id, m.Friendship.friend_id == user_id)
        )
    )
    session.execute(
        delete(m.UserBlock).where(
            or_(m.UserBlock.user_id == user_id, m.UserBlock.blocked_user_id == user_id)
        )
    )
    session.execute(
        delete(m.Share).where(or_(m.Share.sender_id == user_id, m.Share.recipient_id == user_id))
    )
    session.execute(delete(m.AbuseReport).where(m.AbuseReport.reporter_id == user_id))
    session.execute(
        update(m.AbuseReport)
        .where(m.AbuseReport.reported_user_id == user_id)
        .values(reported_user_id=None)
    )
