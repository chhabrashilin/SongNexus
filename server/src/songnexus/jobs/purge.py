"""Purge job: expired sessions, invites and link flows; old reports; deleted accounts.

Scheduled daily (Cloud Scheduler → Cloud Run job ``songnexus-purge``). Deleted
accounts are already empty at deletion time; this removes the remaining row and
its audit trail, completing AC-18.4 within the 30-day promise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from songnexus.storage import (
    accounts_repository,
    community_repository,
    games_repository,
    social_repository,
)
from songnexus.storage import user_repository as users
from songnexus.storage.db import session_scope

DELETED_ACCOUNT_RETENTION = timedelta(days=30)
# Abuse reports keep a copy of the reported note for moderators, then go (ADR 0007).
REPORT_RETENTION = timedelta(days=90)
# Community charts (aggregates only) are kept for movement and rising: a week plus 28 days.
COMMUNITY_CHART_RETENTION = timedelta(days=36)
# Game scores feed the day and week leaderboards; a little over a week back is enough.
GAME_SCORE_RETENTION = timedelta(days=15)
# First trivia answers only matter until the day's score window closes (ADR 0010).
TRIVIA_ANSWER_RETENTION = timedelta(days=2)
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
        charts = community_repository.purge_charts(session, now - COMMUNITY_CHART_RETENTION)
        scores, answers = games_repository.purge(
            session, now - GAME_SCORE_RETENTION, now - TRIVIA_ANSWER_RETENTION
        )
    return {
        "expiredGameScores": scores,
        "expiredTriviaAnswers": answers,
        "expiredCommunityCharts": charts,
        "expiredSessions": sessions,
        "deletedAccounts": accounts,
        "expiredLinkFlows": flows,
        "expiredInvites": invites,
        "expiredReports": reports,
    }
