"""Around you through the API: directory, charts behind the privacy floors, memberships.

Covers: listing and searching communities, charts locked below 10 listeners and
unlocked at exactly 10, the 3-listener artist floor, counts only as ranges, that
no response ever carries a member's ID, the membership lifecycle (join, switch,
leave, export, account deletion), CSRF on writes, the kill switch, synthetic
members, migration 0008 up and down, and the seed command's refusals.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select

from songnexus.catalog.communities import load_directory
from songnexus.cli import main as cli_main
from songnexus.config import Settings
from songnexus.core import community as core
from songnexus.core import ids
from songnexus.jobs import community_seed
from songnexus.service import community_job
from songnexus.service.app import build_state, create_app
from songnexus.service.deps import AppState
from songnexus.storage import community_repository as repo
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope
from tests.service.databases import fresh_database_url, migrated_with_catalog
from tests.service.test_identity import FakeVerifier, reason, sign_in

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")

DIRECTORY = load_directory()
CAMPUS = next(c for c in DIRECTORY.communities if c.kind is core.Kind.CAMPUS)
OTHER_CAMPUS = next(
    c for c in DIRECTORY.communities if c.kind is core.Kind.CAMPUS and c.id != CAMPUS.id
)
CITY = next(c for c in DIRECTORY.communities if c.kind is core.Kind.CITY)


def _state(tmp_path: Path, **overrides: Any) -> AppState:
    url = fresh_database_url(tmp_path)
    migrated_with_catalog(url, tmp_path)
    settings = Settings(database_url=url, log_json=False, read_model_refresh_s=3600, **overrides)
    built = build_state(settings)
    built.verifier = FakeVerifier()
    return built


@pytest.fixture
def state(tmp_path: Path) -> Iterator[AppState]:
    built = _state(tmp_path)
    yield built
    built.engine.dispose()


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    with TestClient(create_app(state.settings, state), base_url="https://testserver") as c:
        yield c


def add_members(
    engine: Engine,
    community: core.Community,
    count: int,
    artists: dict[str, int],
    *,
    synthetic: bool = False,
) -> list[str]:
    """Adds ``count`` members; ``artists`` maps artist -> how many of them listened."""
    now = datetime.now(UTC)
    user_ids = [str(uuid.uuid4()) for _ in range(count)]
    with session_scope(engine) as session:
        for i, user_id in enumerate(user_ids):
            session.add(m.User(id=user_id, firebase_uid=None, created_at=now, age_confirmed_at=now))
            session.flush()
            session.add(
                m.CommunityMembership(
                    user_id=user_id,
                    kind=community.kind.value,
                    community_id=community.id,
                    joined_at=now,
                    synthetic=synthetic,
                )
            )
            for artist_id, listeners in artists.items():
                if i < listeners:
                    session.add(
                        m.ListeningTally(
                            user_id=user_id,
                            provider="LISTENBRAINZ",
                            artist_id=artist_id,
                            plays=7,
                            last_played_at=now - timedelta(days=1),
                        )
                    )
    return user_ids


def chart(client: TestClient, community: core.Community = CAMPUS) -> dict[str, Any]:
    response = client.get(f"/v1/communities/{community.id}/chart")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- directory ------------------------------------------------------------------------


def test_the_directory_has_campuses_and_cities_from_wikidata() -> None:
    kinds = {k: [c for c in DIRECTORY.communities if c.kind is k] for k in core.Kind}
    assert len(kinds[core.Kind.CAMPUS]) >= 20
    assert len(kinds[core.Kind.CITY]) >= 20
    assert len({c.id for c in DIRECTORY.communities}) == len(DIRECTORY.communities)
    for campus in kinds[core.Kind.CAMPUS]:
        if campus.synthetic:
            assert not campus.wikidata and not campus.website
            continue
        assert campus.wikidata.startswith("Q")
        assert campus.city_id is None or campus.city_id in DIRECTORY.by_id


def test_list_search_and_get_communities(client: TestClient) -> None:
    body = client.get("/v1/communities", params={"kind": "CAMPUS", "pageSize": 5}).json()
    assert len(body["communities"]) == 5
    assert {c["kind"] for c in body["communities"]} == {"CAMPUS"}
    assert body["nextPageToken"]

    found = client.get("/v1/communities", params={"query": CAMPUS.name}).json()
    assert found["communities"][0]["name"] == f"communities/{CAMPUS.id}"

    one = client.get(f"/v1/communities/{CAMPUS.id}").json()
    assert one["displayName"] == CAMPUS.name
    assert one["sourceUrl"].startswith("https://www.wikidata.org/wiki/Q")
    missing = client.get("/v1/communities/no-such-place")
    assert missing.status_code == 404
    assert reason(missing) == "COMMUNITY_NOT_FOUND"


# --- charts and their floors ----------------------------------------------------------


def test_an_empty_community_needs_ten_listeners(client: TestClient) -> None:
    body = chart(client)
    assert body["state"] == "LOCKED"
    assert body["listenersNeeded"] == 10
    assert body["artists"] == []
    assert body["listeners"] is None


def test_nine_listeners_keep_the_chart_locked(client: TestClient, state: AppState) -> None:
    add_members(state.engine, CAMPUS, 9, {ALICE: 9, BOB: 9})
    body = chart(client)
    assert body["state"] == "LOCKED"
    assert body["listenersNeeded"] == 1
    assert body["artists"] == []
    assert body["genres"] == []
    assert body["rising"] == []


def test_members_without_listening_do_not_count(client: TestClient, state: AppState) -> None:
    add_members(state.engine, CAMPUS, 12, {ALICE: 9})
    assert chart(client)["listenersNeeded"] == 1


def test_ten_listeners_unlock_and_an_artist_needs_three(
    client: TestClient, state: AppState
) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10, BOB: 3})
    body = chart(client)
    assert body["state"] == "UNLOCKED"
    assert body["listenersNeeded"] == 0
    assert body["listeners"] == {"min": 10, "max": 24}
    rows = {r["artist"]["name"]: r for r in body["artists"]}
    assert rows[f"artists/{ALICE}"]["rank"] == 1
    assert rows[f"artists/{ALICE}"]["listeners"] == {"min": 10, "max": 24}
    assert rows[f"artists/{BOB}"]["listeners"] == {"min": 3, "max": 4}
    assert body["historyAvailable"] is False
    assert body["demoData"] is False


def test_two_listeners_keep_an_artist_off_the_chart(client: TestClient, state: AppState) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10, BOB: 2})
    names = [r["artist"]["name"] for r in chart(client)["artists"]]
    assert names == [f"artists/{ALICE}"]


def test_no_response_carries_member_ids_or_exact_counts(
    client: TestClient, state: AppState
) -> None:
    members = add_members(state.engine, CAMPUS, 11, {ALICE: 11, BOB: 4})
    responses = [
        client.get(f"/v1/communities/{CAMPUS.id}/chart").text,
        client.get(f"/v1/communities/{CAMPUS.id}").text,
        client.get("/v1/communities", params={"query": CAMPUS.name}).text,
    ]
    for text in responses:
        assert "users/" not in text
        for user_id in members:
            assert user_id not in text
        body = json.loads(text)
        assert "plays" not in text
        assert "eligible" not in text

    body = json.loads(responses[0])

    def numbers(value: Any, key: str = "") -> Iterator[tuple[str, int]]:
        if isinstance(value, dict):
            for k, v in value.items():
                yield from numbers(v, k)
        elif isinstance(value, list):
            for v in value:
                yield from numbers(v, key)
        elif isinstance(value, int) and not isinstance(value, bool):
            yield key, value

    allowed = {"rank", "places", "minListeners", "minArtistListeners", "listenersNeeded"}
    for key, value in numbers(body):
        if key in allowed:
            continue
        # Every other number is a range bound, never the exact 11 or 4.
        assert key in {"min", "max"}, key
        assert value in core.BANDS or value + 1 in core.BANDS


def test_blocked_artists_are_hidden_from_the_viewer(client: TestClient, state: AppState) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10, BOB: 5})
    sign_in(client, "viewer")
    assert client.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{BOB}"}).is_success
    names = [r["artist"]["name"] for r in chart(client)["artists"]]
    assert names == [f"artists/{ALICE}"]


def test_charts_are_cached_until_the_ttl(client: TestClient, state: AppState) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10})
    first = chart(client)
    add_members(state.engine, CAMPUS, 5, {BOB: 5})
    second = chart(client)
    assert second["updateTime"] == first["updateTime"]
    assert len(second["artists"]) == 1


def test_movement_and_rising_against_a_week_old_chart(state: AppState) -> None:
    now = datetime.now(UTC)
    week_ago = core.Chart(12, (core.ArtistRow(ALICE, 1, 12, 50, 0),), (), now - timedelta(days=8))
    with session_scope(state.engine) as session:
        repo.save_chart(session, CAMPUS.id, week_ago.computed_at, week_ago.to_payload())
    add_members(state.engine, CAMPUS, 12, {ALICE: 12, BOB: 6})
    with TestClient(create_app(state.settings, state), base_url="https://testserver") as client:
        body = chart(client)
    rows = {r["artist"]["name"]: r for r in body["artists"]}
    assert body["historyAvailable"] is True
    assert rows[f"artists/{ALICE}"]["movement"] == "SAME"
    assert rows[f"artists/{BOB}"]["movement"] == "NEW"
    assert [r["artist"]["name"] for r in body["rising"]] == [f"artists/{BOB}"]


def test_synthetic_members_count_only_in_development(state: AppState) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10}, synthetic=True)
    with session_scope(state.engine) as session:
        rows, synthetic = repo.member_tallies(session, CAMPUS.id, include_synthetic=False)
        assert rows == []
        assert synthetic is False
        rows, synthetic = repo.member_tallies(session, CAMPUS.id, include_synthetic=True)
        assert len(rows) == 10
        assert synthetic is True
    assert community_job.include_synthetic(Settings(environment="development"))
    assert not community_job.include_synthetic(Settings(environment="production"))


def test_demo_charts_say_so(client: TestClient, state: AppState) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10}, synthetic=True)
    assert chart(client)["demoData"] is True


def test_the_scheduled_job_recomputes_stale_charts(state: AppState) -> None:
    add_members(state.engine, CAMPUS, 10, {ALICE: 10})
    model = state.holder.current() if state.holder.ready else None
    if model is None:
        state.holder.refresh()
        model = state.holder.current()
    first = community_job.run_community_charts(state.engine, state.settings, model)
    assert first == {"communities": 1, "recomputed": 1, "unlocked": 1}
    again = community_job.run_community_charts(state.engine, state.settings, model)
    assert again["recomputed"] == 0


# --- memberships ----------------------------------------------------------------------


def test_membership_needs_sign_in(client: TestClient) -> None:
    response = client.get("/v1/users/me/communities")
    assert response.status_code == 401


def test_membership_lifecycle(client: TestClient, state: AppState) -> None:
    sign_in(client, "listener")
    empty = client.get("/v1/users/me/communities").json()
    assert empty["campus"] is None
    assert empty["city"] is None
    assert empty["hasListeningData"] is False

    joined = client.patch(
        "/v1/users/me/communities",
        params={"updateMask": "campus,city"},
        json={"campus": f"communities/{CAMPUS.id}", "city": f"communities/{CITY.id}"},
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["campus"]["community"]["name"] == f"communities/{CAMPUS.id}"
    assert joined.json()["city"]["community"]["name"] == f"communities/{CITY.id}"

    switched = client.patch(
        "/v1/users/me/communities", json={"campus": f"communities/{OTHER_CAMPUS.id}"}
    ).json()
    assert switched["campus"]["community"]["name"] == f"communities/{OTHER_CAMPUS.id}"
    assert switched["city"]["community"]["name"] == f"communities/{CITY.id}"

    export = client.get("/v1/users/me:export").json()
    assert {(c["kind"], c["community"]) for c in export["communities"]} == {
        ("CAMPUS", f"communities/{OTHER_CAMPUS.id}"),
        ("CITY", f"communities/{CITY.id}"),
    }

    left = client.patch(
        "/v1/users/me/communities", params={"updateMask": "campus"}, json={"campus": ""}
    ).json()
    assert left["campus"] is None
    with session_scope(state.engine) as session:
        rows = session.scalars(select(m.CommunityMembership)).all()
        assert [(r.kind, r.community_id) for r in rows] == [("CITY", CITY.id)]
        actions = [a.action for a in session.scalars(select(m.AuditEntry))]
    assert actions.count("community.join") == 3
    assert actions.count("community.leave") == 1


def test_joining_checks_the_kind_and_the_name(client: TestClient) -> None:
    sign_in(client, "listener")
    wrong = client.patch("/v1/users/me/communities", json={"campus": f"communities/{CITY.id}"})
    assert wrong.status_code == 400
    unknown = client.patch("/v1/users/me/communities", json={"city": "communities/atlantis"})
    assert unknown.status_code == 404
    bad_mask = client.patch("/v1/users/me/communities", params={"updateMask": "friends"}, json={})
    assert bad_mask.status_code == 400


def test_membership_writes_need_the_csrf_token(client: TestClient) -> None:
    sign_in(client, "listener")
    del client.headers["X-CSRF-Token"]
    response = client.patch("/v1/users/me/communities", json={"campus": f"communities/{CAMPUS.id}"})
    assert response.status_code == 403
    assert reason(response) == "CSRF_TOKEN_INVALID"


def test_others_memberships_are_out_of_reach(client: TestClient) -> None:
    sign_in(client, "listener")
    response = client.get(f"/v1/users/{uuid.uuid4()}/communities")
    assert response.status_code == 403


def test_deleting_the_account_removes_memberships(client: TestClient, state: AppState) -> None:
    sign_in(client, "listener")
    client.patch("/v1/users/me/communities", json={"campus": f"communities/{CAMPUS.id}"})
    assert client.delete("/v1/users/me").status_code == 200
    with session_scope(state.engine) as session:
        assert session.scalars(select(m.CommunityMembership)).all() == []


def test_the_kill_switch(tmp_path: Path) -> None:
    built = _state(tmp_path, flags={"community": False})
    try:
        with TestClient(create_app(built.settings, built), base_url="https://testserver") as c:
            for path in ("/v1/communities", f"/v1/communities/{CAMPUS.id}/chart"):
                response = c.get(path)
                assert response.status_code == 503
                assert reason(response) == "FLAG_OFF"
    finally:
        built.engine.dispose()


# --- migration and seed ---------------------------------------------------------------


def test_migration_0008_up_and_down(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    try:
        migrate.upgrade(engine, "0008")
        tables = set(inspect(engine).get_table_names())
        assert {"community_memberships", "community_charts"} <= tables
        migrate.downgrade(engine, "0007")
        tables = set(inspect(engine).get_table_names())
        assert not {"community_memberships", "community_charts"} & tables
        assert "friendships" in tables
        migrate.upgrade(engine)
        assert "community_memberships" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_seed_refuses_outside_development(state: AppState) -> None:
    for environment in ("production", "staging", "demo"):
        with pytest.raises(community_seed.SeedRefusedError, match="only runs in development"):
            community_seed.seed_community(state.engine, environment, CAMPUS, 20, datetime.now(UTC))
        with pytest.raises(community_seed.SeedRefusedError):
            community_seed.remove_synthetic(state.engine, environment, None)
    with session_scope(state.engine) as session:
        assert session.scalars(select(m.CommunityMembership)).all() == []


def test_seed_cli_refuses_outside_development(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from songnexus import config

    monkeypatch.setenv("SONGNEXUS_ENVIRONMENT", "production")
    monkeypatch.setenv("SONGNEXUS_DATABASE_URL", f"sqlite:///{tmp_path / 'x.db'}")
    config.get_settings.cache_clear()
    try:
        code = cli_main(["seed-community", "--campus", CAMPUS.id, "--listeners", "20"])
    finally:
        config.get_settings.cache_clear()
    assert code == 1
    assert "only runs in development" in capsys.readouterr().err


def test_seed_creates_marked_members_and_remove_deletes_them(
    state: AppState, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The test catalog is tiny; let the seed draw from it anyway.
    monkeypatch.setattr(community_seed, "MIN_POOL", 1)
    with pytest.raises(community_seed.SeedRefusedError, match="between"):
        community_seed.seed_community(state.engine, "development", CAMPUS, 0, datetime.now(UTC))
    result = community_seed.seed_community(
        state.engine, "development", CAMPUS, 12, datetime.now(UTC)
    )
    assert result["syntheticListeners"] == 12
    with session_scope(state.engine) as session:
        rows = session.scalars(select(m.CommunityMembership)).all()
        assert len(rows) == 12
        assert all(r.synthetic for r in rows)
        assert {u.firebase_uid for u in session.scalars(select(m.User))} == {None}
        assert repo.latest_chart(session, CAMPUS.id) is not None  # the week-old baseline
    removed = community_seed.remove_synthetic(state.engine, "development", CAMPUS.id)
    assert removed["removedListeners"] == 12
    with session_scope(state.engine) as session:
        assert session.scalars(select(m.CommunityMembership)).all() == []
        assert session.scalars(select(m.User)).all() == []
        assert session.scalars(select(m.ListeningTally)).all() == []
        assert repo.latest_chart(session, CAMPUS.id) is None
