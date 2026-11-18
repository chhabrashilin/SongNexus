"""HTTP caching: ETag/304, cache policy per route class, compression, featured artists."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songnexus.config import Settings
from songnexus.core import ids
from songnexus.identity.tokens import InvalidIdTokenError, VerifiedIdentity
from songnexus.service.app import build_state, create_app
from songnexus.service.routes import catalog
from tests.service.databases import fresh_database_url, migrated_with_catalog

ORIGIN = "http://localhost:5173"
ALICE = f"artists/{ids.artist_id('mb-alice')}"
BOB = f"artists/{ids.artist_id('mb-bob')}"
SHARED = "public, max-age=60, stale-while-revalidate=600"


class FakeVerifier:
    def verify(self, id_token: str) -> VerifiedIdentity:
        if not id_token.startswith("uid:"):
            raise InvalidIdTokenError("bad token")
        return VerifiedIdentity(id_token.removeprefix("uid:"))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    url = fresh_database_url(tmp_path)
    migrated_with_catalog(url, tmp_path)
    settings = Settings(database_url=url, log_json=False, read_model_refresh_s=3600)
    state = build_state(settings)
    state.verifier = FakeVerifier()
    with TestClient(create_app(settings, state), base_url="https://testserver") as c:
        yield c
    state.engine.dispose()


def sign_in(client: TestClient, uid: str) -> str:
    response = client.post(
        "/v1/sessions",
        json={"idToken": f"uid:{uid}", "ageConfirmed": True},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return str(response.json()["csrfToken"])


def test_catalog_reads_get_an_etag_and_answer_304(client: TestClient) -> None:
    url = f"/v1/{ALICE}/connections?pageSize=2"
    first = client.get(url)
    assert first.status_code == 200
    assert first.headers["cache-control"] == SHARED
    etag = first.headers["etag"]
    assert etag.startswith('"')
    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert client.get(url, headers={"If-None-Match": '"other"'}).status_code == 200
    other = client.get(f"/v1/{ALICE}/connections?pageSize=3")
    assert other.headers["etag"] != etag


def test_responses_are_cached_in_memory_and_identical(client: TestClient) -> None:
    url = f"/v1/{ALICE}"
    first, second = client.get(url), client.get(url)
    assert first.headers["x-cache"] == "miss"
    assert second.headers["x-cache"] == "hit"
    assert first.content == second.content
    assert client.app.state.response_cache.stats()["hits"] >= 1  # type: ignore[attr-defined]


def test_errors_are_not_cached_and_are_no_store(client: TestClient) -> None:
    response = client.get("/v1/artists/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers


def test_signed_in_viewers_get_private_uncached_responses(client: TestClient) -> None:
    sign_in(client, "u1")
    for url in (f"/v1/{ALICE}/connections", "/v1/catalog:search?query=Alice"):
        response = client.get(url)
        assert response.headers["cache-control"] == "private, no-store"
        assert "etag" not in response.headers
        assert response.headers.get("x-cache") is None
    for url in ("/v1/users/me", "/v1/sessions/current"):
        assert client.get(url).headers["cache-control"] == "private, no-store"
    anonymous = TestClient(client.app, base_url="https://testserver")
    assert anonymous.get("/v1/catalog:search?query=Alice").headers["x-cache"] == "miss"


def test_blocks_change_a_signed_in_result_but_not_the_shared_one(client: TestClient) -> None:
    url = f"/v1/{ALICE}/connections"
    anonymous = TestClient(client.app, base_url="https://testserver")
    before = anonymous.get(url).json()
    csrf = sign_in(client, "u2")
    blocked = client.post(
        "/v1/users/me/blockedArtists",
        json={"artist": BOB},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert blocked.status_code == 200
    mine = client.get(url).json()
    assert len(mine["connections"]) == len(before["connections"]) - 1
    assert anonymous.get(url).json() == before


def test_large_responses_are_compressed(client: TestClient) -> None:
    response = client.get("/v1/dataSources?pageSize=100", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["etag"]
    assert response.json()["dataSources"]


def test_featured_artists_follow_the_list_and_skip_missing_names(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog, "FEATURED_ARTIST_NAMES", ("Bob", "Nobody In The Catalog", "ALICE"))
    response = client.get("/v1/artists:featured")
    assert response.status_code == 200
    body = response.json()
    assert [a["name"] for a in body["artists"]] == [BOB, ALICE]
    assert body["graphVersion"]
    assert response.headers["cache-control"] == SHARED
