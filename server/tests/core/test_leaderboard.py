"""Leaderboard scoring and aggregation: validation against the day's game, privacy floors."""

from datetime import date

import pytest

from songnexus.core import leaderboard as lb

#  A - B - C - D, and A - E - D (two routes; par 2 via E)
ADJ = {
    "A": {"B": 1.0, "E": 1.0},
    "B": {"A": 1.0, "C": 1.0},
    "C": {"B": 1.0, "D": 1.0},
    "D": {"C": 1.0, "E": 1.0},
    "E": {"A": 1.0, "D": 1.0},
}


def score(moves: list[str]) -> lb.Score:
    return lb.puzzle_score(moves, start="A", target="D", par=2, adjacency=ADJ)


def test_puzzle_points_come_from_the_moves_not_the_client() -> None:
    assert score(["A", "E", "D"]).points == 100
    assert score(["A", "E", "D"]).detail == {"steps": 2, "par": 2}
    assert score(["A", "B", "C", "D"]).points == 85
    long_way = ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B", "C", "D"]
    assert score(long_way).points == lb.PUZZLE_MIN_POINTS


@pytest.mark.parametrize(
    ("moves", "reason"),
    [
        (["B", "C", "D"], "PUZZLE_WRONG_START"),
        (["A", "B", "C"], "PUZZLE_TARGET_NOT_REACHED"),
        (["A", "D"], "PUZZLE_STEP_NOT_CONNECTED"),  # a teleport straight to the target
        (["A", "C", "D"], "PUZZLE_STEP_NOT_CONNECTED"),
        (["D"], "PUZZLE_WRONG_START"),
        ([], "PUZZLE_WRONG_START"),
        (["A", *(["B", "A"] * 11), "E", "D"], "PUZZLE_TOO_MANY_MOVES"),
    ],
)
def test_puzzle_cheating_attempts_are_rejected(moves: list[str], reason: str) -> None:
    with pytest.raises(lb.InvalidPlayError) as caught:
        score(moves)
    assert caught.value.reason == reason


QUESTIONS = {
    "q1": (("a", "b", "c", "d"), "a"),
    "q2": (("e", "f", "g", "h"), "f"),
}


def test_trivia_is_marked_by_the_server() -> None:
    result = lb.trivia_score({"q1": "a", "q2": "e"}, questions=QUESTIONS, locked={})
    assert result.points == 50
    assert result.detail == {"correct": 1, "total": 2}


def test_trivia_first_checked_answer_counts_over_a_corrected_submission() -> None:
    # Checked q2 wrong (and so learned the answer), then submitted the right one.
    result = lb.trivia_score({"q1": "a", "q2": "f"}, questions=QUESTIONS, locked={"q2": False})
    assert result.detail["correct"] == 1


@pytest.mark.parametrize(
    ("answers", "reason"),
    [
        ({"q1": "a"}, "TRIVIA_INCOMPLETE"),
        ({"q1": "a", "q2": "f", "q9": "x"}, "TRIVIA_INCOMPLETE"),
        ({"q1": "a", "q2": "zzz"}, "TRIVIA_UNKNOWN_OPTION"),
    ],
)
def test_trivia_invalid_answers(answers: dict[str, str], reason: str) -> None:
    with pytest.raises(lb.InvalidPlayError) as caught:
        lb.trivia_score(answers, questions=QUESTIONS, locked={})
    assert caught.value.reason == reason


def test_week_is_monday_to_sunday() -> None:
    assert lb.period_days(date(2026, 11, 18), lb.Period.WEEK) == (
        date(2026, 11, 16),
        date(2026, 11, 22),
    )
    assert lb.period_days(date(2026, 11, 18), lb.Period.DAY) == (
        date(2026, 11, 18),
        date(2026, 11, 18),
    )


def test_a_campus_needs_the_minimum_number_of_players() -> None:
    floor = lb.MIN_CAMPUS_PLAYERS
    scores = [lb.PlayerScore(i, "big", 50) for i in range(floor)]
    scores += [lb.PlayerScore(100 + i, "small", 100) for i in range(floor - 1)]
    ranked, below = lb.campus_standings(scores)
    assert [s.campus for s in ranked] == ["big"]
    assert below == {"small": floor - 1}
    # One more player unlocks it, and it ranks first on average.
    ranked, below = lb.campus_standings([*scores, lb.PlayerScore(999, "small", 100)])
    assert [(s.campus, s.rank, s.players) for s in ranked] == [
        ("small", 1, floor),
        ("big", 2, floor),
    ]
    assert below == {}


def test_week_sums_each_player_before_averaging_and_flags_demo_data() -> None:
    floor = lb.MIN_CAMPUS_PLAYERS
    scores = [lb.PlayerScore(i, "c", 40) for i in range(floor)]
    scores += [lb.PlayerScore(0, "c", 60, synthetic=True)]  # player 0's second day
    ranked, _ = lb.campus_standings(scores)
    assert ranked[0].average == pytest.approx((40 * floor + 60) / floor)
    assert ranked[0].demo is True


def test_friend_standings_share_ranks_on_ties() -> None:
    standings = lb.friend_standings([("a", 50), ("b", 80), ("a", 30), ("c", 80)])
    assert [(s.user_id, s.rank, s.points, s.days_played) for s in standings] == [
        ("a", 1, 80, 2),
        ("b", 1, 80, 1),
        ("c", 1, 80, 1),
    ]
    assert [s.rank for s in lb.friend_standings([("a", 3), ("b", 2), ("c", 2), ("d", 1)])] == [
        1,
        2,
        2,
        4,
    ]
