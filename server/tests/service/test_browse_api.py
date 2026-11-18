"""Shelves, genres, recommendations, taste profiles and path tracks on the reference catalog."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.config import Settings
from songnexus.identity.tokens import InvalidIdTokenError, VerifiedIdentity
from songnexus.service.app import build_state, create_app
from songnexus.service.deps import AppState
from songnexus.service.errors import ApiError
from songnexus.service.routes.browse import _day
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope

SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "samples" / "musicbrainz_snapshot.jsonl.gz"
)
pytestmark = [
    pytest.mark.golden,
    pytest.mark.skipif(not SNAPSHOT.exists(), reason="committed snapshot not present"),
]

TODAY = date(2026, 10, 20)
ORIGIN = "http://localhost:5173"
WINDOW = [date(2026, 10, 7) + timedelta(days=i) for i in range(15)]


class FakeVerifier:
    def verify(self, id_token: str) -> VerifiedIdentity:
        if not id_token.startswith("uid:"):
            raise InvalidIdTokenError("bad token")
        return VerifiedIdentity(id_token.removeprefix("uid:"))


@pytest.fixture(scope="module")
def url(tmp_path_factory: pytest.TempPathFactory) -> str:
    url = f"sqlite:///{tmp_path_factory.mktemp('browse') / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, SNAPSHOT)
    engine.dispose()
    return url


def _settings(url: str, **overrides: Any) -> Settings:
    return Settings(
        database_url=url,
        log_json=False,
        read_model_refresh_s=3600,
        rate_limit_analyze_per_minute=100_000,
        rate_limit_read_per_minute=100_000,
        **overrides,
    )


@pytest.fixture(scope="module")
def state(url: str) -> AppState:
    state = build_state(_settings(url))
    state.verifier = FakeVerifier()
    return state


@pytest.fixture(scope="module")
def client(state: AppState) -> Iterator[TestClient]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("songnexus.service.routes.browse._day", lambda value: _day(value, TODAY))
        app = create_app(state.settings, state)
        with TestClient(app, base_url="https://testserver") as test_client:
            yield test_client


@pytest.fixture
def user(state: AppState) -> Iterator[TestClient]:
    """A separate signed-in client (its own cookies) on the same app state."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("songnexus.service.routes.browse._day", lambda value: _day(value, TODAY))
        with TestClient(
            create_app(state.settings, state), base_url="https://testserver"
        ) as signed_in:
            yield signed_in


def sign_in(client: TestClient, uid: str) -> str:
    response = client.post(
        "/v1/sessions",
        json={"idToken": f"uid:{uid}", "ageConfirmed": True},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": body["csrfToken"]})
    return str(body["user"]).removeprefix("users/")


def item_artists(item: dict[str, Any]) -> set[str]:
    if item["artist"]:
        return {item["artist"]["name"]}
    if item["recording"]:
        return {a["name"] for a in item["recording"]["artists"]}
    return set()


def test_day_window() -> None:
    assert _day("2026-10-07", TODAY) == date(2026, 10, 7)
    assert _day("2026-10-21", TODAY) == date(2026, 10, 21)
    for bad in ("2026-10-22", "2026-10-06", "2026-1-7", "nope"):
        with pytest.raises(ApiError):
            _day(bad, TODAY)


def test_shelves_are_ordered_deterministic_and_well_formed(client: TestClient) -> None:
    first = client.get("/v1/shelves")
    assert first.status_code == 200
    body = first.json()
    assert body == client.get("/v1/shelves").json()
    kinds = [s["kind"] for s in body["shelves"]]
    assert kinds[:3] == ["BEHIND_THE_HITS", "SUPER_CONNECTORS", "GENRE_BRIDGES"]
    assert "ON_THIS_DAY" not in kinds  # needs a date
    assert {"GENRE", "DECADE", "LABELS"} <= set(kinds)
    assert len({s["name"] for s in body["shelves"]}) == len(kinds)
    for shelf in body["shelves"]:
        assert 3 <= len(shelf["items"]) <= 12
        assert shelf["messageId"].startswith("shelf.")
        assert (shelf["genre"] is not None) == (shelf["kind"] == "GENRE")
        for item in shelf["items"]:
            assert sum(item[k] is not None for k in ("artist", "recording", "label")) == 1
            assert item["reason"]["messageId"].startswith("reason.")
            assert all(isinstance(v, int | str) for v in item["reason"]["params"].values())
    assert first.headers["cache-control"].startswith("public")


def test_shelf_counts_match_the_catalog(client: TestClient, state: AppState) -> None:
    shelves = {s["kind"]: s for s in client.get("/v1/shelves").json()["shelves"]}
    with session_scope(state.engine) as session:

        def distinct_recordings(artist: str, role: str) -> int:
            return (
                session.scalar(
                    select(func.count(func.distinct(m.RecordingCredit.recording_id))).where(
                        m.RecordingCredit.artist_id == artist.removeprefix("artists/"),
                        m.RecordingCredit.role == role,
                    )
                )
                or 0
            )

        for item in shelves["BEHIND_THE_HITS"]["items"][:5]:
            params = item["reason"]["params"]
            assert params["count"] == distinct_recordings(item["artist"]["name"], "producer")
            assert params["led"] == distinct_recordings(item["artist"]["name"], "primary")
            assert params["count"] >= 2 * params["led"]
        for item in shelves["LABELS"]["items"][:5]:
            label_id = item["label"]["name"].removeprefix("labels/")
            releases = session.scalar(
                select(func.count(func.distinct(m.ReleaseLabel.release_id))).where(
                    m.ReleaseLabel.label_id == label_id
                )
            )
            assert item["reason"]["params"]["count"] == releases
    for item in shelves["SUPER_CONNECTORS"]["items"][:5]:
        artist = item["artist"]["name"]
        total = client.get(f"/v1/{artist}/connections", params={"pageSize": 1}).json()
        assert item["reason"]["params"]["count"] == total["totalSize"]


def test_on_this_day_lists_recordings_from_that_month_and_day(client: TestClient) -> None:
    found = 0
    for day in WINDOW:
        shelves = client.get("/v1/shelves", params={"date": day.isoformat()}).json()["shelves"]
        today = [s for s in shelves if s["kind"] == "ON_THIS_DAY"]
        if not today:
            continue
        found += 1
        assert today[0]["params"] == {"month": day.month, "day": day.day}
        assert shelves.index(today[0]) == 3
        for item in today[0]["items"]:
            recording = item["recording"]
            assert recording["firstReleaseDate"][5:10] == day.isoformat()[5:10]
            assert item["reason"]["params"]["year"] == recording["year"] < day.year
            assert item["reason"]["params"]["yearsAgo"] == day.year - recording["year"]
    assert found
    for bad in ("2026-10-22", "2026-10-06", "20261020"):
        assert client.get("/v1/shelves", params={"date": bad}).status_code == 400


def test_genre_page_and_its_artists(client: TestClient) -> None:
    listed = client.get("/v1/genres", params={"pageSize": 3}).json()["genres"][0]
    genre = client.get(f"/v1/{listed['name']}").json()
    assert genre["displayName"] == listed["displayName"]
    assert genre["artistCount"] == listed["artistCount"]
    assert genre["artistCountWithSubgenres"] == listed["artistCountWithSubgenres"]
    assert genre["topLevel"] == (not listed["parents"])
    totals = [c["artistCountWithSubgenres"] for c in genre["children"]]
    assert totals == sorted(totals, reverse=True)
    pages, token = [], ""
    while True:
        params: dict[str, str | int] = {"pageSize": 10}
        if token:
            params["pageToken"] = token
        page = client.get(f"/v1/{listed['name']}/artists", params=params).json()
        pages.extend(page["artists"])
        token = page["nextPageToken"]
        if not token:
            break
    assert len(pages) == page["totalSize"] == genre["memberCount"]
    assert len({a["artist"]["name"] for a in pages}) == len(pages)
    degrees = [a["collaboratorCount"] for a in pages]
    assert degrees == sorted(degrees, reverse=True)
    assert all(0.2 <= a["genreShare"] <= 1 for a in pages)
    narrow = client.get(f"/v1/{listed['name']}/artists", params={"includeSubgenres": False})
    assert narrow.json()["totalSize"] <= genre["memberCount"]


def test_genre_errors(client: TestClient) -> None:
    missing = "genres/00000000-0000-0000-0000-000000000000"
    assert client.get(f"/v1/{missing}").status_code == 404
    assert client.get(f"/v1/{missing}/artists").status_code == 404
    assert client.get("/v1/genres/not-a-genre").status_code == 400


def _top_artist(client: TestClient) -> str:
    shelves = client.get("/v1/shelves").json()["shelves"]
    connectors = next(s for s in shelves if s["kind"] == "SUPER_CONNECTORS")
    return str(connectors["items"][0]["artist"]["name"])


def test_recommendations_are_unconnected_and_their_reasons_check_out(
    client: TestClient,
) -> None:
    artist = _top_artist(client)
    body = client.get(f"/v1/{artist}:recommend", params={"pageSize": 10}).json()
    assert body["artist"]["name"] == artist
    assert body == client.get(f"/v1/{artist}:recommend", params={"pageSize": 10}).json()
    recommendations = body["recommendations"]
    assert 0 < len(recommendations) <= 10
    scores = [r["score"] for r in recommendations]
    assert scores == sorted(scores, reverse=True)
    for item in recommendations:
        other = item["artist"]["name"]
        assert other != artist
        assert item["reasons"]
        direct = client.get(f"/v1/{artist}/connections/{other.removeprefix('artists/')}")
        assert direct.status_code == 404
        for reason in item["reasons"]:
            assert reason["messageId"].startswith("recommend.")
            if reason["kind"] == "SHARED_COLLABORATORS":
                assert 1 <= len(reason["via"]) <= min(3, reason["params"]["count"])
                for via in reason["via"]:
                    via_id = via["name"].removeprefix("artists/")
                    assert client.get(f"/v1/{artist}/connections/{via_id}").status_code == 200
                    back = client.get(f"/v1/{other}/connections/{via_id}")
                    assert back.status_code == 200
            elif reason["kind"] == "SAME_LABEL":
                assert reason["label"]["name"].startswith("labels/")
            else:
                assert reason["source"]["source"] == "dataSources/listenbrainz"


def test_recommend_errors(client: TestClient) -> None:
    missing = "artists/00000000-0000-0000-0000-000000000000"
    assert client.get(f"/v1/{missing}:recommend").status_code == 404
    assert client.get("/v1/artists/nope:recommend").status_code == 400
    artist = _top_artist(client)
    assert client.get(f"/v1/{artist}:recommend", params={"pageSize": 51}).status_code == 400


def test_blocked_artists_disappear_everywhere(client: TestClient, user: TestClient) -> None:
    artist = _top_artist(client)
    anonymous = client.get(f"/v1/{artist}:recommend").json()["recommendations"]
    target = anonymous[0]["artist"]["name"]
    shelf_artist = client.get("/v1/shelves").json()["shelves"][0]["items"][0]["artist"]["name"]
    sign_in(user, "blocker")
    for blocked in (target, shelf_artist):
        assert user.post("/v1/users/me/blockedArtists", json={"artist": blocked}).is_success
    response = user.get(f"/v1/{artist}:recommend")
    assert response.headers["cache-control"] == "private, no-store"
    names = {r["artist"]["name"] for r in response.json()["recommendations"]}
    vias = {
        v["name"]
        for r in response.json()["recommendations"]
        for x in r["reasons"]
        for v in x["via"]
    }
    assert target not in names | vias
    shelves = user.get("/v1/shelves", params={"date": "2026-10-20"}).json()["shelves"]
    shown = {a for s in shelves for i in s["items"] for a in item_artists(i)}
    assert not {target, shelf_artist} & shown
    profile = user.post("/v1/tasteProfiles:compute", json={"artists": [target, artist]}).json()
    assert profile["artistCount"] == 1
    assert profile["skippedArtistCount"] == 1


def test_compute_taste_profile(client: TestClient) -> None:
    shelves = client.get("/v1/shelves").json()["shelves"]
    picks = [i["artist"]["name"] for s in shelves if s["kind"] == "GENRE" for i in s["items"]]
    missing = "artists/00000000-0000-0000-0000-000000000000"
    response = client.post(
        "/v1/tasteProfiles:compute", json={"artists": [*picks, missing, picks[0]]}
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    profile = response.json()
    assert profile["artistCount"] == len(picks)
    assert profile["skippedArtistCount"] == 1
    assert (
        abs(sum(g["share"] for g in profile["genres"]) - 1) < 0.05 or len(profile["genres"]) == 10
    )
    assert abs(sum(d["share"] for d in profile["decades"]) - 1) < 0.01
    decades = [d["decade"] for d in profile["decades"]]
    assert decades == sorted(decades)
    picked = set(picks)
    for connector in profile["hiddenConnectors"]:
        assert connector["artist"]["name"] not in picked
        assert connector["linkedCount"] == len(connector["linkedTo"]) >= 2
        assert set(connector["linkedTo"]) <= picked
    counts = [c["linkedCount"] for c in profile["hiddenConnectors"]]
    assert counts == sorted(counts, reverse=True)
    pair = profile["surprisingPair"]
    if pair is not None:
        path = client.get(
            f"/v1/{pair['artistA']['name']}:findPath", params={"target": pair["artistB"]["name"]}
        ).json()
        assert len(path["steps"]) == pair["steps"]
    cluster = profile["tightestCluster"]
    if cluster is not None:
        assert cluster["size"] >= cluster["minLinks"] + 1
    assert profile["collaboratorsReached"] > 0
    assert profile == client.post("/v1/tasteProfiles:compute", json={"artists": picks}).json() | {
        "skippedArtistCount": 1
    }


def test_compute_taste_profile_bounds(client: TestClient) -> None:
    assert client.post("/v1/tasteProfiles:compute", json={"artists": []}).status_code == 400
    assert client.post("/v1/tasteProfiles:compute", json={"artists": ["x"]}).status_code == 400
    many = [f"artists/00000000-0000-0000-0000-{i:012d}" for i in range(501)]
    assert client.post("/v1/tasteProfiles:compute", json={"artists": many}).status_code == 400
    unknown = client.post("/v1/tasteProfiles:compute", json={"artists": many[:3]}).json()
    assert unknown["artistCount"] == 0
    assert unknown["skippedArtistCount"] == 3
    assert unknown["genres"] == []
    assert unknown["mostCentral"] is None


def test_signed_in_taste_profile_uses_listening(
    client: TestClient, user: TestClient, state: AppState
) -> None:
    assert client.get("/v1/users/me/tasteProfile").status_code == 401
    user_id = sign_in(user, "listener")
    empty = user.get("/v1/users/me/tasteProfile").json()
    assert empty["artistCount"] == 0
    shelves = client.get("/v1/shelves").json()["shelves"]
    picks = [i["artist"]["name"] for s in shelves if s["kind"] == "GENRE" for i in s["items"]][:8]
    with session_scope(state.engine) as session:
        for n, artist in enumerate(picks):
            session.add(
                m.ListeningTally(
                    user_id=user_id,
                    provider="listenbrainz",
                    artist_id=artist.removeprefix("artists/"),
                    plays=100 - n,
                )
            )
    response = user.get(f"/v1/users/{user_id}/tasteProfile")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["artistCount"] == len(picks)
    assert user.get("/v1/users/someone-else/tasteProfile").status_code == 403


def test_find_path_carries_one_real_recording_per_step(client: TestClient) -> None:
    stories = client.get("/v1/stories", params={"pageSize": 20}).json()["stories"]
    pairs = [
        (s["parts"][0]["artist"]["name"], s["parts"][1]["artist"]["name"])
        for s in stories
        if s["kind"] in {"TWO_STEPS", "SHARED_PRODUCER"}
    ]
    checked = 0
    for a, b in pairs[:4]:
        path = client.get(f"/v1/{a}:findPath", params={"target": b}).json()
        assert path["outcome"] == "FOUND"
        tracks = [s["track"] for s in path["steps"] if s["track"] is not None]
        recordings = [t["recording"] for t in tracks]
        assert len(set(recordings)) == len(recordings) or len(recordings) < len(path["steps"])
        for step in path["steps"]:
            track = step["track"]
            if track is None:
                continue
            checked += 1
            details = client.get(f"/v1/{track['recording']}").json()
            assert details["displayName"] == track["displayName"]
            primary = {c["artist"]["name"] for c in details["credits"] if c["role"] == "primary"}
            assert {x["name"] for x in track["artists"]} == primary
            if track["release"] is None:
                credited = {c["artist"]["name"] for c in details["credits"]}
                assert {step["fromArtist"]["name"], step["toArtist"]["name"]} <= credited
            else:
                assert track["release"] in {x["release"] for x in details["appearances"]}
            if track["year"] is not None:
                assert details["firstReleaseDate"].startswith(str(track["year"]))
    assert checked


def test_flags_switch_features_off(url: str) -> None:
    settings = _settings(
        url, flags={"browse": False, "recommendations": False, "tasteProfile": False}
    )
    with TestClient(create_app(settings, build_state(settings))) as off:
        artist = "artists/00000000-0000-0000-0000-000000000000"
        genre = "genres/00000000-0000-0000-0000-000000000000"
        for path in (
            "/v1/shelves",
            f"/v1/{genre}",
            f"/v1/{genre}/artists",
            f"/v1/{artist}:recommend",
        ):
            assert off.get(path).status_code == 503, path
        posted = off.post("/v1/tasteProfiles:compute", json={"artists": [artist]})
        assert posted.status_code == 503
        assert off.get("/v1/config").json()["flags"]["browse"] is False


def test_every_pair_of_shelf_artists_resolves(client: TestClient) -> None:
    """Every artist a shelf names exists (no dangling resource names)."""
    shelves = client.get("/v1/shelves", params={"date": "2026-10-20"}).json()["shelves"]
    names = sorted({a for s in shelves for i in s["items"] for a in item_artists(i)})
    for name in itertools.islice(names, 0, None, max(1, len(names) // 15)):
        assert client.get(f"/v1/{name}").status_code == 200
