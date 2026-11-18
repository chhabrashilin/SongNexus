"""Game scores and first trivia answers (ADR 0010). Authorization happens in callers.

``period_scores`` returns campus aggregation input with user IDs replaced by
opaque integers; only ``friend_scores`` returns user IDs, and callers pass it
only the viewer and their accepted friends.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from songnexus.storage import models as m


def get_score(session: Session, user_id: str, game: str, day: str) -> m.GameScore | None:
    """Returns the player's score for one game and day, if submitted."""
    return session.get(m.GameScore, (user_id, game, day))


def add_score(
    session: Session,
    *,
    user_id: str,
    game: str,
    day: str,
    points: int,
    detail: dict[str, Any],
    campus_id: str | None,
    now: datetime,
) -> m.GameScore:
    """Stores a score. The primary key makes it one per player, game and day."""
    row = m.GameScore(
        user_id=user_id,
        game=game,
        day=day,
        points=points,
        detail=detail,
        campus_id=campus_id,
        submitted_at=now,
    )
    session.add(row)
    session.flush()
    return row


def scores_of(session: Session, user_id: str, since_day: str) -> list[m.GameScore]:
    """The player's own scores from ``since_day`` on, newest first."""
    return list(
        session.scalars(
            select(m.GameScore)
            .where(m.GameScore.user_id == user_id, m.GameScore.day >= since_day)
            .order_by(m.GameScore.day.desc(), m.GameScore.game)
        )
    )


def period_scores(
    session: Session, game: str, first_day: str, last_day: str, *, include_synthetic: bool
) -> list[tuple[int, str, int, bool]]:
    """Returns (opaque player, campus, points, synthetic) for campus aggregation.

    A score counts for a campus only while its player is still a member of the
    campus it was submitted for (leaving a campus takes its scores out at once).
    Deleted accounts never count.
    """
    query = (
        select(
            m.GameScore.user_id,
            m.GameScore.campus_id,
            m.GameScore.points,
            m.CommunityMembership.synthetic,
        )
        .join(
            m.CommunityMembership,
            (m.CommunityMembership.user_id == m.GameScore.user_id)
            & (m.CommunityMembership.kind == "CAMPUS")
            & (m.CommunityMembership.community_id == m.GameScore.campus_id),
        )
        .join(m.User, m.User.id == m.GameScore.user_id)
        .where(
            m.GameScore.game == game,
            m.GameScore.day >= first_day,
            m.GameScore.day <= last_day,
            m.User.deleted_at.is_(None),
        )
    )
    if not include_synthetic:
        query = query.where(m.CommunityMembership.synthetic.is_(False))
    keys: dict[str, int] = {}
    rows: list[tuple[int, str, int, bool]] = []
    for user_id, campus_id, points, synthetic in session.execute(query):
        rows.append(
            (keys.setdefault(user_id, len(keys)), str(campus_id), int(points), bool(synthetic))
        )
    return rows


def friend_scores(
    session: Session, user_ids: Iterable[str], game: str, first_day: str, last_day: str
) -> list[tuple[str, int]]:
    """Returns (user, points) per scored day for the given people (viewer and friends)."""
    ids = list(user_ids)
    if not ids:
        return []
    return [
        (str(u), int(p))
        for u, p in session.execute(
            select(m.GameScore.user_id, m.GameScore.points).where(
                m.GameScore.user_id.in_(ids),
                m.GameScore.game == game,
                m.GameScore.day >= first_day,
                m.GameScore.day <= last_day,
            )
        )
    ]


def first_answers(session: Session, user_id: str, day: str) -> dict[str, bool]:
    """Question ID to whether the player's first checked answer was right."""
    return {
        row.question_id: row.correct
        for row in session.scalars(
            select(m.TriviaAnswer).where(
                m.TriviaAnswer.user_id == user_id, m.TriviaAnswer.day == day
            )
        )
    }


def record_first_answer(
    session: Session, user_id: str, day: str, question_id: str, *, correct: bool, now: datetime
) -> None:
    """Keeps the first checked answer to a question; later ones are ignored."""
    if session.get(m.TriviaAnswer, (user_id, day, question_id)) is None:
        session.add(
            m.TriviaAnswer(
                user_id=user_id, day=day, question_id=question_id, correct=correct, answered_at=now
            )
        )
        session.flush()


def erase(session: Session, user_id: str) -> None:
    """Deletes the user's scores and first answers now (account deletion)."""
    session.execute(delete(m.GameScore).where(m.GameScore.user_id == user_id))
    session.execute(delete(m.TriviaAnswer).where(m.TriviaAnswer.user_id == user_id))


def purge(session: Session, scores_before: datetime, answers_before: datetime) -> tuple[int, int]:
    """Removes scores and first answers past their retention. Returns both counts."""
    day = scores_before.date().isoformat()
    scores = session.execute(delete(m.GameScore).where(m.GameScore.day < day))
    answers = session.execute(
        delete(m.TriviaAnswer).where(m.TriviaAnswer.answered_at < answers_before)
    )
    return int(scores.rowcount), int(answers.rowcount)  # type: ignore[attr-defined]
