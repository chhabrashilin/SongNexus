"""Campus leaderboards for the daily puzzle and Credit check (ADR 0010). Pure.

Scores are never taken from the client. A player submits their play (the
puzzle moves, or the quiz answers) and the server computes the points here,
against the day's puzzle or quiz:

* Puzzle: the moves must start at the day's start, end at its target, and every
  step must be a real connection. ``PUZZLE_MAX_POINTS`` at par, minus
  ``PUZZLE_STEP_PENALTY`` per extra step, never below ``PUZZLE_MIN_POINTS``.
* Credit check: every question answered exactly once with one of its options.
  Points are the share of right answers, out of ``TRIVIA_MAX_POINTS``.

Leaderboards mirror the Around you privacy rules: a campus appears only when at
least ``MIN_CAMPUS_PLAYERS`` members scored in the period; it shows an average
(rounded) and a player range, never a person. Individual scores are visible
only to accepted friends (the friends leaderboard).
"""

from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

# Mirrors MIN_CHART_LISTENERS: an average over fewer players says too much about each.
MIN_CAMPUS_PLAYERS = 10
MAX_CAMPUSES = 10
PUZZLE_MAX_POINTS = 100
PUZZLE_MIN_POINTS = 10
PUZZLE_STEP_PENALTY = 15
# A solved puzzle longer than this is not a plausible play; it bounds request work too.
MAX_PUZZLE_MOVES = 20
TRIVIA_MAX_POINTS = 100


class Game(enum.StrEnum):
    """A game with a leaderboard."""

    PUZZLE = "PUZZLE"
    TRIVIA = "TRIVIA"


class Period(enum.StrEnum):
    """What a leaderboard covers: one day, or the ISO week (Monday to Sunday) of a day."""

    DAY = "DAY"
    WEEK = "WEEK"


class InvalidPlayError(ValueError):
    """A submitted play does not fit the day's puzzle or quiz.

    Attributes:
        reason: A stable machine-readable reason (``PUZZLE_WRONG_START``, ...).
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Score:
    """Points computed by the server, with what they were computed from."""

    points: int
    max_points: int
    detail: Mapping[str, int]


def puzzle_score(
    moves: Sequence[str],
    *,
    start: str,
    target: str,
    par: int,
    adjacency: Mapping[str, Mapping[str, float]],
) -> Score:
    """Scores a solved puzzle from its moves (``start`` first, ``target`` last).

    Raises:
        InvalidPlayError: The moves don't solve the day's puzzle.
    """
    if len(moves) - 1 > MAX_PUZZLE_MOVES:
        raise InvalidPlayError("PUZZLE_TOO_MANY_MOVES", f"At most {MAX_PUZZLE_MOVES} steps.")
    if not moves or moves[0] != start:
        raise InvalidPlayError("PUZZLE_WRONG_START", "The moves must begin at today's start.")
    if moves[-1] != target or len(moves) < 2:  # noqa: PLR2004 (a step needs two artists)
        raise InvalidPlayError("PUZZLE_TARGET_NOT_REACHED", "The moves must reach the target.")
    for a, b in pairwise(moves):
        if b not in adjacency.get(a, {}):
            raise InvalidPlayError(
                "PUZZLE_STEP_NOT_CONNECTED", "Every step must be a connection in our data."
            )
    steps = len(moves) - 1
    return Score(puzzle_points(steps, par), PUZZLE_MAX_POINTS, {"steps": steps, "par": par})


def puzzle_points(steps: int, par: int) -> int:
    """Points for a puzzle solved in ``steps`` (par is the shortest possible)."""
    extra = max(0, steps - par)
    return max(PUZZLE_MIN_POINTS, PUZZLE_MAX_POINTS - PUZZLE_STEP_PENALTY * extra)


def trivia_points(correct: int, total: int) -> int:
    """Points for ``correct`` right answers out of ``total``."""
    return round(TRIVIA_MAX_POINTS * correct / total) if total else 0


def trivia_score(
    answers: Mapping[str, str],
    *,
    questions: Mapping[str, tuple[Sequence[str], str]],
    locked: Mapping[str, bool],
) -> Score:
    """Scores a Credit check.

    Args:
        answers: Question ID to the chosen option.
        questions: Question ID to (its options, the right option).
        locked: Questions the player already checked: whether the first answer was
            right. These count as checked, whatever ``answers`` says now.

    Raises:
        InvalidPlayError: A question is missing, unknown or has a foreign option.
    """
    if set(answers) != set(questions):
        raise InvalidPlayError("TRIVIA_INCOMPLETE", "Answer every question exactly once.")
    correct = 0
    for question_id, (options, right) in questions.items():
        chosen = answers[question_id]
        if chosen not in options:
            raise InvalidPlayError("TRIVIA_UNKNOWN_OPTION", "That is not one of the options.")
        first = locked.get(question_id)
        correct += int(first if first is not None else chosen == right)
    total = len(questions)
    return Score(
        trivia_points(correct, total), TRIVIA_MAX_POINTS, {"correct": correct, "total": total}
    )


def period_days(day: date, period: Period) -> tuple[date, date]:
    """Returns the first and last day (inclusive) a leaderboard covers."""
    if period is Period.DAY:
        return day, day
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


@dataclass(frozen=True)
class PlayerScore:
    """One score for aggregation. ``player`` is opaque and never leaves this module."""

    player: int
    campus: str
    points: int
    synthetic: bool = False


@dataclass(frozen=True)
class CampusStanding:
    """A campus on the leaderboard. ``players`` is internal: served only as a range."""

    campus: str
    rank: int
    players: int
    average: float
    demo: bool


def campus_standings(scores: Iterable[PlayerScore]) -> tuple[list[CampusStanding], dict[str, int]]:
    """Ranks campuses by their members' average points over the period.

    A player's points are summed over the period first, so the week rewards
    playing every day. Campuses below ``MIN_CAMPUS_PLAYERS`` are left out.

    Returns:
        Every ranked campus (best first; callers show the top ``MAX_CAMPUSES``),
        and the player count of each campus that is below the floor (for "N more
        players needed" on the viewer's own campus only).
    """
    totals: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    demo: dict[str, bool] = defaultdict(bool)
    for score in scores:
        totals[score.campus][score.player] += score.points
        demo[score.campus] = demo[score.campus] or score.synthetic
    ranked: list[tuple[float, int, str]] = []
    below: dict[str, int] = {}
    for campus, players in totals.items():
        if len(players) < MIN_CAMPUS_PLAYERS:
            below[campus] = len(players)
            continue
        ranked.append((sum(players.values()) / len(players), len(players), campus))
    ranked.sort(key=lambda r: (-round(r[0]), -r[1], r[2]))
    standings = [
        CampusStanding(campus, rank, players, average, demo[campus])
        for rank, (average, players, campus) in enumerate(ranked, start=1)
    ]
    return standings, below


@dataclass(frozen=True)
class FriendStanding:
    """A friend (or the viewer) on the friends leaderboard."""

    user_id: str
    rank: int
    points: int
    days_played: int


def friend_standings(scores: Iterable[tuple[str, int]]) -> list[FriendStanding]:
    """Ranks people by points summed over the period; ``scores`` are (user, points) per day.

    Callers pass only the viewer's and accepted friends' scores. Ties share a rank.
    """
    points: dict[str, int] = defaultdict(int)
    days: dict[str, int] = defaultdict(int)
    for user_id, value in scores:
        points[user_id] += value
        days[user_id] += 1
    order = sorted(points, key=lambda u: (-points[u], -days[u], u))
    standings: list[FriendStanding] = []
    for index, user_id in enumerate(order):
        tied = standings and standings[-1].points == points[user_id]
        rank = standings[-1].rank if tied else index + 1
        standings.append(FriendStanding(user_id, rank, points[user_id], days[user_id]))
    return standings
