"""Credit check trivia and stories on the real reference catalog."""

import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.config import Settings
from songnexus.core import trivia
from songnexus.service.app import build_state, create_app
from songnexus.service.errors import ApiError
from songnexus.service.routes.discover import _day
from songnexus.storage import migrate
from songnexus.storage.db import make_engine

SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
)

pytestmark = [
    pytest.mark.golden,
    pytest.mark.skipif(not SNAPSHOT.exists(), reason="committed snapshot not present"),
]

TODAY = date(2026, 10, 20)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path_factory.mktemp('discover') / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, SNAPSHOT)
    settings = Settings(
        database_url=url,
        log_json=False,
        read_model_refresh_s=3600,
        rate_limit_analyze_per_minute=100_000,
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("songnexus.service.routes.discover._day", lambda value: _day(value, TODAY))
        with TestClient(create_app(settings, build_state(settings))) as test_client:
            yield test_client


def test_day_window() -> None:
    assert _day("2026-10-07", TODAY) == trivia.LAUNCH_DAY
    assert _day("2026-10-21", TODAY) == date(2026, 10, 21)  # UTC+14 players
    for bad in ("2026-10-22", "2026-10-06", "2026-1-7", "nope", "2026-10-20T00:00"):
        with pytest.raises(ApiError):
            _day(bad, TODAY)


def test_trivia_is_deterministic_and_has_no_answers(client: TestClient) -> None:
    first = client.get("/v1/trivia/2026-10-12")
    assert first.status_code == 200
    quiz = first.json()
    assert quiz == client.get("/v1/trivia/2026-10-12").json()
    assert quiz["number"] == 6
    assert quiz["name"] == "trivia/2026-10-12"
    assert len(quiz["questions"]) == trivia.QUESTIONS_PER_DAY
    for q in quiz["questions"]:
        assert len(q["options"]) == trivia.OPTIONS_PER_QUESTION
        assert len({o["name"] for o in q["options"]}) == trivia.OPTIONS_PER_QUESTION
    text = json.dumps(quiz).lower()
    for leak in ("answer", "correct", "evidence"):
        assert leak not in text
    other = client.get("/v1/trivia/2026-10-13").json()
    assert other["questions"] != quiz["questions"]


def test_past_dates_allowed_future_rejected(client: TestClient) -> None:
    assert client.get("/v1/trivia/2026-10-07").status_code == 200
    for bad in ("2026-10-22", "2026-10-06", "garbage"):
        response = client.get(f"/v1/trivia/{bad}")
        assert response.status_code == 400, bad
    posted = client.post(
        "/v1/trivia/2026-10-30:check", json={"question": "q1", "option": "artists/x"}
    )
    assert posted.status_code == 400


def test_exactly_one_option_is_correct_and_it_is_proven(client: TestClient) -> None:
    for offset in range(10):
        day = (trivia.LAUNCH_DAY + timedelta(days=offset)).isoformat()
        quiz = client.get(f"/v1/trivia/{day}").json()
        for q in quiz["questions"]:
            verdicts = []
            for option in q["options"]:
                response = client.post(
                    f"/v1/trivia/{day}:check", json={"question": q["id"], "option": option["name"]}
                )
                assert response.status_code == 200, response.text
                body = response.json()
                verdicts.append(body["correct"])
                assert body["correctOption"]["name"] in {o["name"] for o in q["options"]}
                if q["kind"] == "WHICH_LABEL":
                    assert body["sources"]
                else:
                    assert body["evidence"]
                    assert all(e["sources"] for e in body["evidence"])
            assert verdicts.count(True) == 1


def test_distractors_are_never_credited_on_the_song(client: TestClient) -> None:
    model = client.app.state.songnexus.holder.current()  # type: ignore[attr-defined]
    index = trivia.build_index(model.graph)
    for offset in range(40):
        day = trivia.LAUNCH_DAY + timedelta(days=offset)
        quiz = trivia.quiz_for(day, index)
        assert quiz == trivia.quiz_for(day, index)
        answers = {q.answer for q in quiz.questions}
        assert len(answers) == len(quiz.questions)
        for q in quiz.questions:
            assert q.answer in q.options
            wrong = [o for o in q.options if o != q.answer]
            assert len(wrong) == trivia.OPTIONS_PER_QUESTION - 1
            if q.kind is trivia.QuestionKind.WORKED_WITH:
                everyone = model.graph.neighbors[q.artist_id]
                assert not set(wrong) & set(everyone)
                assert q.answer in everyone
            else:
                credited = index.credited[q.subject_id]
                assert not set(wrong) & credited
                assert q.answer in credited


def test_check_rejects_unknown_question_and_option(client: TestClient) -> None:
    quiz = client.get("/v1/trivia/2026-10-08").json()
    bad_q = client.post("/v1/trivia/2026-10-08:check", json={"question": "q9", "option": "x"})
    assert bad_q.status_code == 400
    outside = client.post(
        "/v1/trivia/2026-10-08:check",
        json={"question": "q1", "option": "artists/00000000-0000-0000-0000-000000000000"},
    )
    assert outside.status_code == 400
    assert quiz["questions"]


def test_stories_paginate_deterministically_with_evidence(client: TestClient) -> None:
    pages = []
    token = ""
    while True:
        response = client.get("/v1/stories", params={"pageSize": 10, "pageToken": token})
        assert response.status_code == 200
        body = response.json()
        pages.append(body)
        token = body["nextPageToken"]
        if not token:
            break
    stories = [s for p in pages for s in p["stories"]]
    assert len(stories) == pages[0]["totalSize"] > 20
    assert len({s["name"] for s in stories}) == len(stories)
    again = client.get("/v1/stories", params={"pageSize": 10}).json()
    assert again["stories"] == pages[0]["stories"]
    kinds = {s["kind"] for s in stories}
    assert {"SHARED_PRODUCER", "TWO_STEPS", "SESSION_PLAYER"} <= kinds
    for story in stories:
        assert story["credits"], story["name"]
        assert story["messageId"].startswith("story.")
        assert all(c["sources"] for c in story["credits"]), story["name"]
        assert story["parts"]


def test_stories_reject_a_stale_or_forged_token(client: TestClient) -> None:
    assert client.get("/v1/stories", params={"pageToken": "nonsense"}).status_code == 400


def test_flags_switch_features_off(client: TestClient) -> None:
    state = client.app.state.songnexus  # type: ignore[attr-defined]
    saved = dict(state.flags)
    try:
        state.flags["stories"] = False
        assert client.get("/v1/stories").status_code == 503
        state.flags["play"] = False
        assert client.get("/v1/trivia/2026-10-07").status_code == 503
    finally:
        state.flags.update(saved)
    assert client.get("/v1/stories").status_code == 200


def test_path_challenge_is_deterministic_and_far_apart(client: TestClient) -> None:
    model = client.app.state.songnexus.holder.current()  # type: ignore[attr-defined]
    first = client.get("/v1/pathChallenges/2026-10-10").json()
    assert first == client.get("/v1/pathChallenges/2026-10-10").json()
    assert 3 <= first["steps"] <= 5
    assert first["fromArtist"]["name"] != first["toArtist"]["name"]
    assert client.get("/v1/pathChallenges/2026-10-30").status_code == 400
    assert model.version == first["graphVersion"]
