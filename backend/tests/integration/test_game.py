"""SongNexus Daily on the synthetic graph.

Fully loaded artists are Alpha, Gamma and Zeta. Only Alpha and Zeta are 3 steps apart
(Alpha → Delta → Gamma → Zeta, or via Epsilon), so every daily puzzle is that pair.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from songnexus.core.config import Settings
from songnexus.core.errors import InvalidRequestError
from songnexus.core.ids import artist_id_for_mbid
from songnexus.readmodel import ReadModelStore
from songnexus.schemas.api import GameCheckRequest
from songnexus.services.game_service import LAUNCH_DAY, GameService
from songnexus.services.graph_service import GraphService
from tests.fixtures import mbid


def aid(key: str) -> str:
    return artist_id_for_mbid(mbid(key))


@pytest.fixture
def game(loaded_engine: Engine, settings: Settings) -> GameService:
    return GameService(GraphService(ReadModelStore(loaded_engine), settings))


def test_daily_puzzle_is_fair_deterministic_and_numbered(game: GameService) -> None:
    first = game.daily(LAUNCH_DAY)
    assert first.number == 1 and first.par == 3
    assert {first.start.id, first.target.id} == {aid("alpha"), aid("zeta")}
    assert game.daily(LAUNCH_DAY) == first  # same puzzle for everyone
    assert game.daily(LAUNCH_DAY + timedelta(days=9)).number == 10


def test_correct_step_reveals_evidence_and_distance(game: GameService) -> None:
    result = game.check(GameCheckRequest(from_id=aid("alpha"), to_id=aid("delta"), target_id=aid("zeta")))
    assert result.connected and not result.reached_target
    assert result.distance_to_target == 2
    assert result.evidence[0].sentence == "Delta Producer produced Alpha Rapper's “Skyline”"


def test_wrong_step_reveals_nothing(game: GameService) -> None:
    result = game.check(GameCheckRequest(from_id=aid("alpha"), to_id=aid("zeta"), target_id=aid("zeta")))
    assert not result.connected and result.evidence == [] and result.distance_to_target is None
    assert not result.reached_target


def test_reaching_the_target(game: GameService) -> None:
    result = game.check(GameCheckRequest(from_id=aid("gamma"), to_id=aid("zeta"), target_id=aid("zeta")))
    assert result.connected and result.reached_target and result.distance_to_target == 0


def test_hint_always_offers_a_step_closer(game: GameService) -> None:
    hint = game.hint(aid("alpha"), aid("zeta"))
    names = {c.name for c in hint.candidates}
    assert "Delta Producer" in names  # the only neighbor that gets closer
    assert game.hint(aid("alpha"), aid("zeta")) == hint  # same hint for everyone


def test_same_artist_is_rejected(game: GameService) -> None:
    with pytest.raises(InvalidRequestError):
        game.check(GameCheckRequest(from_id=aid("alpha"), to_id=aid("alpha"), target_id=aid("zeta")))


def test_game_endpoints(client: TestClient) -> None:
    puzzle = client.get("/api/v1/game/daily", params={"date": LAUNCH_DAY.isoformat()}).json()
    assert puzzle["par"] == 3
    check = client.post(
        "/api/v1/game/check",
        json={"from_id": puzzle["start"]["id"], "to_id": aid("delta"), "target_id": puzzle["target"]["id"]},
    ).json()
    assert "connected" in check
    solution = client.get("/api/v1/game/solution", params={"date": LAUNCH_DAY.isoformat()}).json()
    assert solution["found"] and solution["path"]["length"] == 3
    hint = client.get(
        "/api/v1/game/hint", params={"from_id": puzzle["start"]["id"], "target_id": puzzle["target"]["id"]}
    )
    assert hint.status_code == 200


def test_no_future_or_pre_launch_puzzles(client: TestClient) -> None:
    future = datetime.now(UTC).date() + timedelta(days=3)
    assert client.get("/api/v1/game/daily", params={"date": future.isoformat()}).status_code == 400
    assert client.get("/api/v1/game/daily", params={"date": date(2020, 1, 1).isoformat()}).status_code == 400
    assert client.get("/api/v1/game/daily").status_code == 200  # today
