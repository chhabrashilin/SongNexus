"""Game scores and leaderboards through the API (ADR 0010).

Covers: scores computed server side from the play (cheating attempts rejected),
one score per game per day, the score window, the trivia first-answer lock, the
campus floor (9 players hidden, 10 shown), the viewer's campus rank, leaving a
campus taking its scores out, the friends leaderboard showing only accepted
friends, export and deletion, sign-in and the kill switch, migration 0010.
"""

import contextlib
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select

from songnexus.catalog.communities import load_directory
from songnexus.config import Settings
from songnexus.core import community as cc
from songnexus.core import game, ids, trivia
from songnexus.core import leaderboard as lb
from songnexus.service.app import build_state
from songnexus.service.deps import AppState
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage import social_repository as social
from songnexus.storage.db import make_engine, session_scope
from tests.service.databases import fresh_database_url, migrated_with_catalog
from tests.service.test_identity import FakeVerifier, new_client, reason, sign_in

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
CAROL = ids.artist_id("mb-carol")
BAND = ids.artist_id("mb-band")
TODAY = datetime.now(UTC).date()
DAY = TODAY.isoformat()

DIRECTORY = load_directory()
CAMPUSES = [c for c in DIRECTORY.communities if c.kind is cc.Kind.CAMPUS][:3]


def fake_puzzle(_model: Any, day: date) -> game.Puzzle:
    return game.Puzzle(day, 1, BOB, CAROL, 2)  # Bob - Alice - Carol


def fake_quiz(_model: Any, _session: Any, day: date) -> trivia.Quiz:
    options = (ALICE, BOB, CAROL, BAND)
    return trivia.Quiz(
        day,
        1,
        (
            trivia.Question("q1", trivia.QuestionKind.WORKED_WITH, options, BOB, "", "", ALICE),
            trivia.Question("q2", trivia.QuestionKind.WORKED_WITH, options, CAROL, "", "", ALICE),
        ),
    )


def _state(tmp_path: Path, **overrides: Any) -> AppState:
    url = fresh_database_url(tmp_path)
    migrated_with_catalog(url, tmp_path)
    settings = Settings(database_url=url, log_json=False, read_model_refresh_s=3600, **overrides)
    built = build_state(settings)
    built.verifier = FakeVerifier()
    return built


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppState]:
    monkeypatch.setattr("songnexus.service.routes.play._puzzle", fake_puzzle)
    monkeypatch.setattr("songnexus.service.routes.discover._quiz", fake_quiz)
    built = _state(tmp_path)
    with contextlib.ExitStack() as stack:
        OPEN[id(built)] = stack
        yield built
    built.engine.dispose()


OPEN: dict[int, contextlib.ExitStack] = {}


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    with new_client(state) as c:
        yield c


def player(state: AppState, uid: str, campus: cc.Community | None = None) -> tuple[TestClient, str]:
    c = OPEN[id(state)].enter_context(new_client(state))
    user = sign_in(c, uid)["user"].removeprefix("users/")
    assert c.patch("/v1/users/me/socialProfile", json={"displayName": uid}).status_code == 200
    if campus is not None:
        r = c.patch("/v1/users/me/communities", json={"campus": f"communities/{campus.id}"})
        assert r.status_code == 200, r.text
    return c, user


def solve(c: TestClient, moves: list[str] | None = None, day: str = DAY) -> Any:
    return c.post(
        f"/v1/puzzles/{day}:submitScore",
        json={"moves": [f"artists/{a}" for a in (moves or [BOB, ALICE, CAROL])]},
    )


def add_scores(
    engine: Engine,
    campus: cc.Community,
    points: list[int],
    *,
    game_name: str = "PUZZLE",
    day: str = DAY,
    synthetic: bool = False,
) -> list[str]:
    """Adds one member of ``campus`` per entry, each with a stored score."""
    now = datetime.now(UTC)
    user_ids = [str(uuid.uuid4()) for _ in points]
    with session_scope(engine) as session:
        for user_id, value in zip(user_ids, points, strict=True):
            session.add(m.User(id=user_id, firebase_uid=None, created_at=now, age_confirmed_at=now))
            session.flush()
            session.add(
                m.CommunityMembership(
                    user_id=user_id,
                    kind="CAMPUS",
                    community_id=campus.id,
                    joined_at=now,
                    synthetic=synthetic,
                )
            )
            session.add(
                m.GameScore(
                    user_id=user_id,
                    game=game_name,
                    day=day,
                    points=value,
                    detail={},
                    campus_id=campus.id,
                    submitted_at=now,
                )
            )
    return user_ids


# --- submission and validation ---------------------------------------------------------


def test_puzzle_score_is_computed_by_the_server_once_per_day(state: AppState) -> None:
    c, user = player(state, "ana", CAMPUSES[0])
    response = solve(c, [BOB, ALICE, BAND, ALICE, CAROL])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == f"users/{user}/gameScores/PUZZLE-{DAY}"
    assert (body["points"], body["steps"], body["par"]) == (70, 4, 2)
    assert body["campus"] == f"communities/{CAMPUSES[0].id}"
    assert body["synthetic"] is False

    again = solve(c)
    assert again.status_code == 409
    assert reason(again) == "SCORE_ALREADY_SUBMITTED"
    listed = c.get("/v1/users/me/gameScores").json()["gameScores"]
    assert [s["points"] for s in listed] == [70]


@pytest.mark.parametrize(
    ("moves", "expected"),
    [
        ([ALICE, CAROL], "PUZZLE_WRONG_START"),
        ([BOB, ALICE], "PUZZLE_TARGET_NOT_REACHED"),
        ([BOB, BAND, CAROL], "PUZZLE_STEP_NOT_CONNECTED"),
    ],
)
def test_puzzle_cheating_attempts(state: AppState, moves: list[str], expected: str) -> None:
    c, _ = player(state, "cheat")
    response = solve(c, moves)
    assert response.status_code == 400
    assert reason(response) == expected
    assert c.get("/v1/users/me/gameScores").json()["gameScores"] == []


def test_a_client_supplied_points_field_is_ignored_or_refused(state: AppState) -> None:
    c, _ = player(state, "liar")
    response = c.post(
        f"/v1/puzzles/{DAY}:submitScore",
        json={"moves": [f"artists/{a}" for a in (BOB, ALICE, BAND, ALICE, CAROL)], "points": 100},
    )
    if response.status_code == 200:
        assert response.json()["points"] == 70
    else:
        assert response.status_code == 400


def test_scores_only_for_today(state: AppState) -> None:
    c, _ = player(state, "late")
    for day in (TODAY - timedelta(days=3), TODAY + timedelta(days=3)):
        response = solve(c, day=day.isoformat())
        assert response.status_code == 400
        assert reason(response) == "SCORE_WINDOW_CLOSED"
    assert solve(c, day="2026-1-1").status_code == 400


def test_submitting_requires_sign_in_csrf_and_the_flag(state: AppState, client: TestClient) -> None:
    assert reason(solve(client)) == "SIGN_IN_REQUIRED"
    c, _ = player(state, "csrf")
    c.headers.pop("X-CSRF-Token")
    assert reason(solve(c)) == "CSRF_TOKEN_INVALID"
    state.flags["leaderboards"] = False
    off = client.get("/v1/leaderboards/campuses", params={"game": "PUZZLE"})
    assert off.status_code == 503
    assert reason(off) == "FLAG_OFF"


def test_trivia_is_marked_server_side_and_the_first_checked_answer_counts(
    state: AppState,
) -> None:
    c, _ = player(state, "quiz")
    wrong = c.post(f"/v1/trivia/{DAY}:check", json={"question": "q1", "option": f"artists/{ALICE}"})
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["correct"] is False
    # Now "knowing" the answer, submit it as if answered right the first time.
    answers = [
        {"question": "q1", "option": f"artists/{BOB}"},
        {"question": "q2", "option": f"artists/{CAROL}"},
    ]
    response = c.post(f"/v1/trivia/{DAY}:submitScore", json={"answers": answers})
    assert response.status_code == 200, response.text
    assert (response.json()["correct"], response.json()["total"], response.json()["points"]) == (
        1,
        2,
        50,
    )


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ([{"question": "q1", "option": f"artists/{BOB}"}], "TRIVIA_INCOMPLETE"),
        (
            [
                {"question": "q1", "option": f"artists/{BOB}"},
                {"question": "q1", "option": f"artists/{BOB}"},
            ],
            "TRIVIA_INCOMPLETE",
        ),
        (
            [
                {"question": "q1", "option": f"artists/{BOB}"},
                {"question": "q2", "option": f"artists/{uuid.uuid4()}"},
            ],
            "TRIVIA_UNKNOWN_OPTION",
        ),
    ],
)
def test_trivia_invalid_submissions(
    state: AppState, answers: list[dict[str, str]], expected: str
) -> None:
    c, _ = player(state, "bad-quiz")
    response = c.post(f"/v1/trivia/{DAY}:submitScore", json={"answers": answers})
    assert response.status_code == 400
    assert reason(response) == expected


# --- campus leaderboard ---------------------------------------------------------------


def board(c: TestClient, **params: str) -> dict[str, Any]:
    response = c.get("/v1/leaderboards/campuses", params={"game": "PUZZLE", **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_campus_leaderboard_floor_average_and_viewer_rank(state: AppState) -> None:
    big, small, other = CAMPUSES
    add_scores(state.engine, big, [50] * 10)
    add_scores(state.engine, small, [100] * (lb.MIN_CAMPUS_PLAYERS - 2))
    c, _ = player(state, "viewer", small)
    assert solve(c).status_code == 200  # 100 points; small now has 9 players

    body = board(c)
    assert [s["community"]["name"] for s in body["campuses"]] == [f"communities/{big.id}"]
    assert body["campuses"][0]["averagePoints"] == 50
    assert body["campuses"][0]["players"] == {"min": 10, "max": 24}
    assert body["minPlayers"] == lb.MIN_CAMPUS_PLAYERS
    assert body["viewerCampus"]["state"] == "NEEDS_PLAYERS"
    assert body["viewerCampus"]["playersNeeded"] == 1
    assert "user" not in str(body)  # no person anywhere

    add_scores(state.engine, small, [100])  # the tenth player
    body = board(c)
    assert [s["community"]["name"] for s in body["campuses"]] == [
        f"communities/{small.id}",
        f"communities/{big.id}",
    ]
    assert body["viewerCampus"]["state"] == "RANKED"
    assert body["viewerCampus"]["rank"] == 1

    # Leaving the campus takes the viewer's score out at once.
    assert c.patch("/v1/users/me/communities", json={"campus": ""}).status_code == 200
    body = board(c)
    assert [s["community"]["name"] for s in body["campuses"]] == [f"communities/{big.id}"]
    assert body["viewerCampus"]["state"] == "NO_CAMPUS"
    del other


def test_week_board_and_anonymous_viewers(state: AppState, client: TestClient) -> None:
    campus = CAMPUSES[0]
    monday = TODAY - timedelta(days=TODAY.weekday())
    add_scores(state.engine, campus, [40] * 10, day=monday.isoformat())
    body = board(client, period="WEEK", date=DAY)
    assert body["startDate"] == monday.isoformat()
    assert body["campuses"][0]["averagePoints"] == 40
    assert body["viewerCampus"] is None
    assert body["demoData"] is False
    assert (
        board(client, period="DAY", date=(monday - timedelta(days=1)).isoformat())["campuses"] == []
    )


def test_synthetic_scores_count_only_in_development_and_are_flagged(
    state: AppState, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_scores(state.engine, CAMPUSES[0], [60] * 10, synthetic=True)
    body = board(client)
    assert body["demoData"] is True
    assert len(body["campuses"]) == 1
    # Outside development synthetic members never count (community_job.include_synthetic).
    monkeypatch.setattr("songnexus.service.community_job.include_synthetic", lambda _s: False)
    assert board(client)["campuses"] == []


# --- friends leaderboard --------------------------------------------------------------


def test_friend_leaderboard_shows_only_accepted_friends(state: AppState) -> None:
    ana, ana_id = player(state, "ana")
    ben, ben_id = player(state, "ben")
    _, cy_id = player(state, "cy")
    with session_scope(state.engine) as session:
        social.befriend(session, ana_id, ben_id, datetime.now(UTC))
    assert solve(ana).status_code == 200
    assert solve(ben, [BOB, ALICE, BAND, ALICE, CAROL]).status_code == 200
    stranger, _ = player(state, "stranger")
    assert solve(stranger).status_code == 200

    response = ana.get("/v1/users/me/friendLeaderboard", params={"game": "PUZZLE"})
    assert response.status_code == 200, response.text
    standings = response.json()["standings"]
    assert [
        (s["person"]["displayName"], s["rank"], s["points"], s["isViewer"]) for s in standings
    ] == [
        ("ana", 1, 100, True),
        ("ben", 2, 70, False),
    ]
    other = ana.get(f"/v1/users/{cy_id}/friendLeaderboard", params={"game": "PUZZLE"})
    assert reason(other) == "NOT_YOUR_RESOURCE"

    # A block ends the friendship: ben disappears from ana's board.
    assert (
        ana.post("/v1/users/me/blockedUsers", json={"user": f"users/{ben_id}"}).status_code == 200
    )
    standings = ana.get("/v1/users/me/friendLeaderboard", params={"game": "PUZZLE"}).json()[
        "standings"
    ]
    assert [s["person"]["displayName"] for s in standings] == ["ana"]


# --- lifecycle --------------------------------------------------------------------------


def test_scores_are_exported_and_erased_with_the_account(state: AppState) -> None:
    c, user = player(state, "leaver", CAMPUSES[0])
    assert solve(c).status_code == 200
    c.post(f"/v1/trivia/{DAY}:check", json={"question": "q1", "option": f"artists/{BOB}"})
    exported = c.get("/v1/users/me:export").json()
    assert exported["gameScores"][0]["points"] == 100
    assert exported["triviaFirstAnswers"] == [{"date": DAY, "question": "q1", "correct": True}]
    assert exported["social"]["shareTopArtists"] is False
    assert c.delete("/v1/users/me").status_code == 200
    with session_scope(state.engine) as session:
        assert session.scalars(select(m.GameScore).where(m.GameScore.user_id == user)).all() == []
        assert (
            session.scalars(select(m.TriviaAnswer).where(m.TriviaAnswer.user_id == user)).all()
            == []
        )


def test_migration_0010_up_and_down(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    try:
        migrate.upgrade(engine)
        tables = set(inspect(engine).get_table_names())
        assert {"game_scores", "trivia_answers"} <= tables
        assert "synthetic_source" in {c["name"] for c in inspect(engine).get_columns("users")}
        migrate.downgrade(engine, "0009")
        tables = set(inspect(engine).get_table_names())
        assert not {"game_scores", "trivia_answers"} & tables
        assert "synthetic_source" not in {c["name"] for c in inspect(engine).get_columns("users")}
        migrate.upgrade(engine)
    finally:
        engine.dispose()
