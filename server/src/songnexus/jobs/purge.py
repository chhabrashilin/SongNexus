"""Purge job: expired sessions, invites and link flows; old reports; deleted accounts.

Scheduled daily (Cloud Scheduler → Cloud Run job ``songnexus-purge``). Deleted
accounts are already empty at deletion time; this removes the remaining row and
its audit trail, completing AC-18.4 within the 30-day promise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from songnexus.storage import accounts_repository, social_repository
from songnexus.storage import user_repository as users
from songnexus.storage.db import session_scope

DELETED_ACCOUNT_RETENTION = timedelta(days=30)
# Abuse reports keep a copy of the reported note for moderators, then go (ADR 0007).
REPORT_RETENTION = timedelta(days=90)
# Margin so the 30-day promise holds even if a daily run is missed.
_SAFETY_MARGIN = timedelta(days=2)


def run_purge(engine: Engine, now: datetime | None = None) -> dict[str, int]:
    """Runs the purge and returns what it removed."""
    now = now or datetime.now(UTC)
    with session_scope(engine) as session:
        sessions = users.purge_expired_sessions(session, now)
        accounts = users.purge_deleted_users(
            session, now - (DELETED_ACCOUNT_RETENTION - _SAFETY_MARGIN)
        )
        flows = accounts_repository.purge_flows(session, now)
        invites = social_repository.purge_invites(session, now)
        reports = social_repository.purge_reports(session, now - REPORT_RETENTION)
    return {
        "expiredSessions": sessions,
        "deletedAccounts": accounts,
        "expiredLinkFlows": flows,
        "expiredInvites": invites,
        "expiredReports": reports,
    }
