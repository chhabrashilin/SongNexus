"""Play (US-04) on the real reference catalog: fairness, rules and the API contract."""

import logging
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.config import Settings
from songnexus.core import game
from songnexus.core.graph.algorithms import bidirectional_bfs_path
from songnexus.service.app import build_state, create_app
from songnexus.service.errors import ApiError
from songnexus.service.routes.play import KINDS, _day, _puzzle
from songnexus.storage import migrate
from songnexus.storage.db import make_engine

SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
)

pytestmark = [
    pytest.mark.golden,
    pytest.mark.skipif(not SNAPSHOT.exists(), reason="committed snapshot not present"),
]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path_factory.mktemp('play') / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, SNAPSHOT)
    settings = Settings(database_url=url, log_json=False, read_model_refresh_s=3600)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "songnexus.service.routes.play._day", lambda value: _day(value, date(2026, 10, 8))
        )
        with TestClient(create_app(settings, build_state(settings))) as test_client:
            yield test_client


def today() -> str:
    return game.LAUNCH_DAY.isoformat()


def check(client: TestClient, day: str, a: str, b: str) -> dict[str, Any]:
    response = client.post(f"/v1/puzzles/{day}:checkMove", json={"fromArtist": a, "toArtist": b})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_every_day_for_a_year_is_fair_and_the_same_for_everyone(client: TestClient) -> None:
    """AC-4.1: identical for all players, solvable, par 3-4 (checked for 365 days)."""
    model = client.app.state.songnexus.holder.current()  # type: ignore[attr-defined]
    adjacency = model.graph.adjacency(KINDS)
    for offset in range(365):
        day = game.LAUNCH_DAY + timedelta(days=offset)
        puzzle = _puzzle(model, day)
        assert puzzle == _puzzle(model, day)
        assert game.MIN_PAR <= puzzle.par <= game.MAX_PAR
        nodes = model.graph.nodes
        assert nodes[puzzle.start].detail_level == nodes[puzzle.target].detail_level == "full"
        path = bidirectional_bfs_path(adjacency, puzzle.start, puzzle.target).path
        assert path is not None
        assert len(path) - 1 == puzzle.par


def test_get_daily_puzzle(client: TestClient) -> None:
    first = client.get(f"/v1/puzzles/{today()}")
    assert first.status_code == 200
    puzzle = first.json()
    assert puzzle == client.get(f"/v1/puzzles/{today()}").json()
    assert puzzle["name"] == f"puzzles/{today()}"
    assert puzzle["start"]["name"] != puzzle["target"]["name"]
    assert first.headers["cache-control"] == "public, max-age=300"


def test_dates_outside_the_window_are_refused() -> None:
    utc_today = date(2026, 12, 1)
    assert _day("2026-12-02", utc_today) == date(2026, 12, 2)  # UTC+14 is a day ahead
    for bad in ("2026-12-03", "2026-10-06", "12/01/2026", "20261201", "2026-02-30"):
        with pytest.raises(ApiError) as error:
            _day(bad, utc_today)
        assert error.value.metadata["field"] == "date"


def test_a_wrong_move_reveals_nothing(client: TestClient) -> None:
    """AC-4.2."""
    puzzle = client.get(f"/v1/puzzles/{today()}").json()
    # The target itself is never directly connected to the start (par >= 3).
    result = check(client, today(), puzzle["start"]["name"], puzzle["target"]["name"])
    assert result == {
        "connected": False,
        "artist": None,
        "evidence": [],
        "stepsToTarget": None,
        "reachedTarget": False,
    }


def test_solving_with_the_revealed_route(client: TestClient) -> None:
    """AC-4.2: each correct move shows evidence and the steps left, down to the target."""
    puzzle = client.get(f"/v1/puzzles/{today()}").json()
    reveal = client.get(f"/v1/puzzles/{today()}:reveal").json()
    assert len(reveal["steps"]) == puzzle["par"]
    assert all(step["evidence"] and step["evidence"][0]["sources"] for step in reveal["steps"])
    remaining = []
    for step in reveal["steps"]:
        result = check(client, today(), step["fromArtist"]["name"], step["toArtist"]["name"])
        assert result["connected"]
        assert result["evidence"]
        assert all(e["sources"] for e in result["evidence"])
        remaining.append(result["stepsToTarget"])
    assert remaining == list(range(puzzle["par"] - 1, -1, -1))
    assert result["reachedTarget"]


def test_hints_include_a_step_closer(client: TestClient) -> None:
    puzzle = client.get(f"/v1/puzzles/{today()}").json()
    hints = client.post(
        f"/v1/puzzles/{today()}:hint", json={"fromArtist": puzzle["start"]["name"]}
    ).json()["candidates"]
    assert len(hints) == game.HINT_SIZE
    steps = [
        check(client, today(), puzzle["start"]["name"], h["name"])["stepsToTarget"] for h in hints
    ]
    assert min(s for s in steps if s is not None) == puzzle["par"] - 1


def test_invalid_moves_are_rejected(client: TestClient) -> None:
    response = client.post(
        f"/v1/puzzles/{today()}:checkMove", json={"fromArtist": "nope", "toArtist": "nope"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"][0]["metadata"]["field"] == "fromArtist"


def test_share_emits_one_counter_event(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="songnexus.service.routes.play"):
        response = client.post("/v1/puzzles:share")
    assert response.status_code == 204
    assert response.content == b""
    events = [record for record in caplog.records if record.getMessage() == "game.share"]
    assert len(events) == 1
    assert events[0].__dict__["metric"] == "game.share"
    assert events[0].__dict__["value"] == 1
