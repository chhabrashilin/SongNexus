"""``songnexus seed-demo`` on the committed reference catalog.

Covers: refusal outside development and over a real ``demo`` account; that every
account is labeled synthetic with a fictional handle and no identity except the
demo account; that re-running gives the same data (idempotent); charts built
through the production path with the privacy floors intact (the 8-member campus
stays locked and off the leaderboard); weekly movers from the stored snapshots;
the demo account's screens through local sign-in; and that ``--reset`` removes
exactly what the seed created.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from songnexus import config
from songnexus.catalog.ingest import ingest_snapshot
from songnexus.cli import main as cli_main
from songnexus.config import Settings
from songnexus.jobs import demo_seed
from songnexus.service.app import build_state, create_app
from songnexus.storage import community_repository, migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope
from tests.service.test_identity import ORIGIN

SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
)

pytestmark = [
    pytest.mark.golden,
    pytest.mark.skipif(not SNAPSHOT.exists(), reason="committed snapshot not present"),
]


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> str:
    url = f"sqlite:///{tmp_path_factory.mktemp('demo') / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, SNAPSHOT)
    engine.dispose()
    return url


def run(
    monkeypatch: pytest.MonkeyPatch, url: str, *args: str, environment: str = "development"
) -> int:
    monkeypatch.setenv("SONGNEXUS_ENVIRONMENT", environment)
    monkeypatch.setenv("SONGNEXUS_DATABASE_URL", url)
    monkeypatch.setenv("SONGNEXUS_FIREBASE_PROJECT_ID", "")
    config.get_settings.cache_clear()
    try:
        return cli_main(["seed-demo", *args])
    finally:
        config.get_settings.cache_clear()


def snapshot(url: str) -> dict[str, Any]:
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            users = session.scalars(
                select(m.User).where(m.User.synthetic_source == demo_seed.SOURCE)
            ).all()
            ids = {u.id for u in users}

            def count(model: Any, column: Any) -> int:
                return int(
                    session.scalar(select(func.count()).select_from(model).where(column.in_(ids)))
                    or 0
                )

            return {
                "ids": ids,
                "identities": sorted(u.firebase_uid for u in users if u.firebase_uid),
                "tallies": count(m.ListeningTally, m.ListeningTally.user_id),
                "memberships": count(m.CommunityMembership, m.CommunityMembership.user_id),
                "unlabeledMemberships": int(
                    session.scalar(
                        select(func.count())
                        .select_from(m.CommunityMembership)
                        .where(
                            m.CommunityMembership.user_id.in_(ids),
                            m.CommunityMembership.synthetic.is_(False),
                        )
                    )
                    or 0
                ),
                "scores": count(m.GameScore, m.GameScore.user_id),
                "friendships": count(m.Friendship, m.Friendship.user_id),
                "shares": count(m.Share, m.Share.recipient_id),
                "names": [
                    p.display_name
                    for p in session.scalars(
                        select(m.SocialProfile).where(m.SocialProfile.user_id.in_(ids))
                    )
                ],
                "charts": int(
                    session.scalar(select(func.count()).select_from(m.CommunityChart)) or 0
                ),
            }
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def seeded(database: str) -> Iterator[str]:
    with pytest.MonkeyPatch.context() as patch:
        assert run(patch, database) == 0
    return database


def test_refuses_outside_development_and_over_a_real_demo_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'x.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        session.add(
            m.User(id="real", firebase_uid="local:demo", created_at=now, age_confirmed_at=now)
        )
    engine.dispose()
    for environment in ("production", "staging"):
        assert run(monkeypatch, url, environment=environment) == 1
        assert "only runs in development" in capsys.readouterr().err
        assert run(monkeypatch, url, "--reset", environment=environment) == 1
    assert run(monkeypatch, url) == 1
    assert "real account already signs in as 'demo'" in capsys.readouterr().err


def test_everything_is_labeled_and_fictional(seeded: str) -> None:
    state = snapshot(seeded)
    members = sum(p.members for p in demo_seed.PLAN)
    assert len(state["ids"]) == members + 1
    assert state["identities"] == ["local:demo"]  # only the demo account can sign in
    assert state["unlabeledMemberships"] == 0
    assert state["friendships"] == 2 * len(demo_seed.FRIENDS)
    assert state["shares"] == len(demo_seed.FRIENDS)
    assert state["scores"] > 0
    assert all(n.endswith("(demo)") or n == "Demo Listener (you)" for n in state["names"])


def test_rerunning_is_idempotent(seeded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    before = snapshot(seeded)
    assert run(monkeypatch, seeded) == 0
    after = snapshot(seeded)
    assert after["ids"] == before["ids"]
    for key in ("tallies", "memberships", "friendships", "shares", "charts"):
        assert after[key] == before[key], key


def test_charts_leaderboards_movers_and_the_demo_account(seeded: str) -> None:
    settings = Settings(database_url=seeded, log_json=False, read_model_refresh_s=3600)
    state = build_state(settings)
    try:
        with TestClient(create_app(settings, state), base_url="https://testserver") as c:
            big = c.get("/v1/communities/university-of-wisconsin-madison/chart").json()
            assert big["state"] == "UNLOCKED"
            assert big["demoData"] is True
            assert big["historyAvailable"] is True
            small = c.get("/v1/communities/demo-br-1/chart").json()
            assert small["state"] == "LOCKED"  # 8 members: the floor still holds
            assert small["artists"] == []

            movers = c.get("/v1/communities/university-of-wisconsin-madison/weeklyMovers").json()
            assert movers["state"] == "AVAILABLE"
            assert movers["demoData"] is True
            assert movers["entered"] or movers["rose"] or movers["fell"]
            assert c.get("/v1/communities/demo-br-1/weeklyMovers").json()["state"] == "LOCKED"

            board = c.get("/v1/leaderboards/campuses", params={"game": "PUZZLE"}).json()
            names = [s["community"]["name"] for s in board["campuses"]]
            assert names
            assert "communities/demo-br-1" not in names
            assert board["demoData"] is True

            signed = c.post(
                "/v1/sessions:local",
                json={"listener": "demo", "ageConfirmed": True},
                headers={"Origin": ORIGIN},
            )
            assert signed.status_code == 200, signed.text
            assert signed.json()["newUser"] is False
            c.headers.update({"Origin": ORIGIN, "X-CSRF-Token": signed.json()["csrfToken"]})
            mine = c.get("/v1/users/me/communities").json()
            assert mine["campus"]["community"]["name"] == "communities/demo-us-1"
            assert mine["hasListeningData"] is True
            friends = c.get("/v1/users/me/friends").json()["friends"]
            assert len(friends) == len(demo_seed.FRIENDS)
            inbox = c.get("/v1/users/me/inbox").json()
            assert inbox["totalSize"] == len(demo_seed.FRIENDS)
            assert inbox["unreadCount"] == 3
            assert c.get("/v1/users/me/gameScores").json()["gameScores"]
            ranked = c.get("/v1/leaderboards/campuses", params={"game": "PUZZLE"}).json()
            assert ranked["viewerCampus"]["community"]["name"] == "communities/demo-us-1"
            friend_board = c.get(
                "/v1/users/me/friendLeaderboard", params={"game": "PUZZLE", "period": "WEEK"}
            ).json()
            assert len(friend_board["standings"]) > 1

            sharing = friends[0]["person"]["user"].removeprefix("users/")
            not_sharing = friends[demo_seed.NOT_SHARING_FRIEND]["person"]["user"].removeprefix(
                "users/"
            )
            found = c.get(f"/v1/users/me/friends/{sharing}/paths")
            assert found.status_code == 200, found.text
            assert found.json()["demoData"] is True
            refused = c.get(f"/v1/users/me/friends/{not_sharing}/paths")
            assert refused.json()["error"]["details"][0]["reason"] == "FRIEND_NOT_SHARING"
    finally:
        state.engine.dispose()


def test_reset_removes_only_what_the_seed_created(
    seeded: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(seeded)
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        session.add(
            m.User(id="a-real-one", firebase_uid="uid:real", created_at=now, age_confirmed_at=now)
        )
        session.flush()
        other_seed = community_repository.add_synthetic_member(
            session, "CAMPUS", "university-of-toronto", {}, now
        )
    engine.dispose()

    assert run(monkeypatch, seeded, "--reset") == 0
    state = snapshot(seeded)
    assert state["ids"] == set()
    engine = make_engine(seeded)
    try:
        with session_scope(engine) as session:
            assert session.get(m.User, "a-real-one") is not None
            assert session.get(m.User, other_seed) is not None
            assert session.scalars(select(m.GameScore)).all() == []
            demo_charts = [
                c for c in session.scalars(select(m.CommunityChart)) if c.payload.get("demo")
            ]
            assert demo_charts == []
    finally:
        engine.dispose()
    assert run(monkeypatch, seeded) == 0  # and it can be seeded again
