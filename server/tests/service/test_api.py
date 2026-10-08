"""API contract tests against a real (SQLite) catalog built from synthetic records."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.musicbrainz.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.service.app import build_state, create_app
from songnexus.storage import migrate
from songnexus.storage.db import make_engine
from tests.catalog import fixtures as fx

ALICE = f"artists/{ids.artist_id('mb-alice')}"
BOB = f"artists/{ids.artist_id('mb-bob')}"
BAND = f"artists/{ids.artist_id('mb-band')}"
CAROL = f"artists/{ids.artist_id('mb-carol')}"
MISSING = "artists/00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("api")
    snapshot = root / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    url = f"sqlite:///{root / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    return Settings(
        database_url=url, data_dir=Path(root), log_json=False, read_model_refresh_s=3600
    )


@pytest.fixture(scope="module")
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, build_state(settings))) as test_client:
        yield test_client


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert error["code"] == response.status_code
    (detail,) = error["details"]
    assert detail["@type"] == "type.googleapis.com/google.rpc.ErrorInfo"
    assert detail["domain"] == "songnexus.app"
    return error


def test_health_and_config(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "catalogLoaded": True}
    config = client.get("/v1/config").json()
    assert config["flags"]["sixDegrees"] is True
    assert config["flags"]["play"] is False  # QA Q12: not shipped yet
    assert config["limits"] == {
        "maxQueryLength": 120,
        "maxPathSteps": 6,
        "maxAlternatives": 3,
        "maxPageSize": 100,
    }
    assert config["graphVersion"].endswith("+run1")


def test_security_headers_and_request_id(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-Id": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" in response.headers
    bad_id = client.get("/healthz", headers={"X-Request-Id": "bad id\twith spaces"})
    assert bad_id.headers["x-request-id"] != "bad id\twith spaces"


def test_get_artist(client: TestClient) -> None:
    response = client.get(f"/v1/{ALICE}")
    assert response.status_code == 200
    artist = response.json()
    assert artist["name"] == ALICE
    assert artist["displayName"] == "Alice"
    assert artist["detailLevel"] == "full"
    assert {g["displayName"] for g in artist["genres"]} == {"Hip-Hop", "jazz"}
    assert {"displayName": "アリス", "aliasType": "artist_name", "locale": "ja"} in artist[
        "aliases"
    ]
    assert artist["links"] == [{"linkType": "official homepage", "url": "https://alice.example"}]
    assert artist["sources"][0]["url"] == "https://musicbrainz.org/artist/mb-alice"
    assert artist["connectionCount"] == 3  # Bob, Carol, The Band
    assert response.headers["cache-control"] == "public, max-age=300"


def test_errors_use_the_canonical_envelope(client: TestClient) -> None:
    missing = client.get(f"/v1/{MISSING}")
    error = error_of(missing)
    assert (missing.status_code, error["status"]) == (404, "NOT_FOUND")
    assert error["details"][0]["reason"] == "ARTIST_NOT_FOUND"

    malformed = client.get("/v1/artists/not-a-uuid")
    assert error_of(malformed)["status"] == "INVALID_ARGUMENT"

    no_route = client.get("/v1/nothing-here")
    assert error_of(no_route)["details"][0]["reason"] == "ROUTE_NOT_FOUND"

    bad_query = client.get(f"/v1/{ALICE}:findPath", params={"target": BOB, "maxSteps": 9})
    error = error_of(bad_query)
    assert error["status"] == "INVALID_ARGUMENT"
    assert error["details"][0]["metadata"]["field"] == "maxSteps"


def test_list_connections_paginates_with_opaque_tokens(client: TestClient) -> None:
    first = client.get(f"/v1/{ALICE}/connections", params={"pageSize": 2}).json()
    assert first["totalSize"] == 3
    assert len(first["connections"]) == 2
    assert first["nextPageToken"]
    second = client.get(
        f"/v1/{ALICE}/connections", params={"pageSize": 2, "pageToken": first["nextPageToken"]}
    ).json()
    assert len(second["connections"]) == 1
    assert second["nextPageToken"] == ""
    names = [c["artist"]["name"] for c in first["connections"] + second["connections"]]
    assert sorted(names) == sorted([BOB, CAROL, BAND])
    # The band (member_of, weight 3) is the strongest connection.
    assert first["connections"][0]["artist"]["name"] == BAND

    reused = client.get(
        f"/v1/{ALICE}/connections",
        params={"pageSize": 2, "pageToken": first["nextPageToken"], "orderBy": "displayName"},
    )
    assert error_of(reused)["status"] == "INVALID_ARGUMENT"
    garbage = client.get(f"/v1/{ALICE}/connections", params={"pageToken": "%%%"})
    assert error_of(garbage)["details"][0]["metadata"]["field"] == "pageToken"


def test_connection_categories_filter_kinds(client: TestClient) -> None:
    bands_only = client.get(f"/v1/{ALICE}/connections", params={"categories": "BANDS"}).json()
    assert [c["artist"]["name"] for c in bands_only["connections"]] == [BAND]
    assert bands_only["connections"][0]["kinds"] == ["MEMBER_OF"]


def test_connection_detail_has_evidence_with_sources(client: TestClient) -> None:
    detail = client.get(f"/v1/{ALICE}/connections/{ids.artist_id('mb-bob')}").json()
    assert detail["kinds"] == ["PERFORMED_WITH"]
    (evidence,) = detail["evidence"]
    assert evidence["messageId"] == "evidence.featured"
    assert (evidence["fromRole"], evidence["toRole"]) == ("primary", "featured")
    assert evidence["subject"]["displayName"] == "Song"
    urls = {s["url"] for s in evidence["sources"]}
    # Both the original and the merged remaster are cited.
    assert urls == {
        "https://musicbrainz.org/recording/rec-1",
        "https://musicbrainz.org/recording/rec-3",
    }

    relation = client.get(f"/v1/{ALICE}/connections/{ids.artist_id('mb-band')}").json()
    assert relation["evidence"][0]["sources"][0]["url"] == "https://musicbrainz.org/artist/mb-alice"

    unconnected = client.get(f"/v1/{BOB}/connections/{ids.artist_id('mb-band')}")
    assert error_of(unconnected)["details"][0]["reason"] == "CONNECTION_NOT_FOUND"


def test_collaborations(client: TestClient) -> None:
    response = client.get(f"/v1/{ALICE}/collaborations", params={"type": "FEATURE"}).json()
    assert [c["artist"]["name"] for c in response["collaborations"]] == [BOB]
    assert response["collaborations"][0]["count"] == 1
    assert response["counts"] == {"FEATURE": 1, "PRODUCTION": 1, "BAND": 1, "CREDIT": 0}


def test_find_path(client: TestClient) -> None:
    found = client.get(f"/v1/{BOB}:findPath", params={"target": BAND}).json()
    assert found["outcome"] == "FOUND"
    assert [s["fromArtist"]["name"] for s in found["steps"]] == [BOB, ALICE]
    assert found["steps"][-1]["toArtist"]["name"] == BAND
    assert all(step["evidence"] and step["evidence"][0]["sources"] for step in found["steps"])

    strongest = client.get(
        f"/v1/{BOB}:findPath", params={"target": BAND, "mode": "STRONGEST_LINKS"}
    ).json()
    assert strongest["outcome"] == "FOUND"

    too_short = client.get(f"/v1/{BOB}:findPath", params={"target": BAND, "maxSteps": 1}).json()
    assert too_short == {
        "outcome": "NOT_CONNECTED_WITHIN_LIMIT",
        "steps": [],
        "alternatives": [],
        "graphVersion": found["graphVersion"],
    }

    unknown_genre = client.get(
        f"/v1/{BOB}:findPath", params={"target": BAND, "genres": f"genres/{MISSING[8:]}"}
    )
    assert error_of(unknown_genre)["details"][0]["reason"] == "GENRE_NOT_FOUND"


def test_compare(client: TestClient) -> None:
    result = client.get(f"/v1/{BOB}:compare", params={"other": CAROL}).json()
    assert [a["name"] for a in result["mutualCollaborators"]] == [ALICE]
    # Carol produced "Song", which Bob features on.
    assert result["directlyConnected"] is True
    assert [a["name"] for a in result["path"]] == [BOB, CAROL]
    assert result["genreOverlap"] is None  # Carol has no genre data


def test_recording(client: TestClient) -> None:
    song_id = ids.recording_id(f"song|{ids.artist_id('mb-alice')}")
    recording = client.get(f"/v1/recordings/{song_id}").json()
    assert recording["displayName"] == "Song"
    roles = {(c["artist"]["name"], c["role"]) for c in recording["credits"]}
    assert roles == {(ALICE, "primary"), (BOB, "featured"), (CAROL, "producer")}
    assert {a["displayName"] for a in recording["appearances"]} == {"First Album", "Best Of"}


def test_search(client: TestClient) -> None:
    results = client.get("/v1/catalog:search", params={"query": "アリス"}).json()["results"]
    assert results[0]["name"] == ALICE
    assert results[0]["entityType"] == "ARTIST"
    assert results[0]["matchedOn"] == "アリス"

    releases = client.get(
        "/v1/catalog:search", params={"query": "album", "types": "RELEASE"}
    ).json()["results"]
    assert {r["entityType"] for r in releases} == {"RELEASE"}

    too_long = client.get("/v1/catalog:search", params={"query": "x" * 121})
    assert error_of(too_long)["details"][0]["metadata"]["field"] == "query"


def test_genres(client: TestClient) -> None:
    genres = client.get("/v1/genres").json()
    assert genres["totalSize"] == 3
    assert {g["displayName"] for g in genres["genres"]} == {"Hip-Hop", "jazz", "R&B"}


def test_openapi_is_served_and_names_methods(client: TestClient) -> None:
    spec = client.get("/v1/openapi.json").json()
    summaries = {op["summary"] for path in spec["paths"].values() for op in path.values()}
    assert {"GetArtist", "ListArtistConnections", "FindPath", "SearchCatalog"} <= summaries


def test_rate_limit_returns_resource_exhausted(settings: Settings) -> None:
    strict = settings.model_copy(update={"rate_limit_analyze_per_minute": 2})
    with TestClient(create_app(strict, build_state(strict))) as limited:
        params = {"target": BAND}
        statuses = [limited.get(f"/v1/{BOB}:findPath", params=params).status_code for _ in range(3)]
        assert statuses == [200, 200, 429]
        blocked = limited.get(f"/v1/{BOB}:findPath", params=params)
        assert error_of(blocked)["status"] == "RESOURCE_EXHAUSTED"
        assert int(blocked.headers["retry-after"]) >= 1
        # Other method classes have their own budget.
        assert limited.get(f"/v1/{ALICE}").status_code == 200


def test_error_bodies_match_the_documented_schema(client: TestClient) -> None:
    from songnexus.service.schemas import ErrorResponse

    for response in (
        client.get(f"/v1/{MISSING}"),
        client.get("/v1/artists/not-a-uuid"),
        client.get("/v1/catalog:search"),
    ):
        ErrorResponse.model_validate(response.json())
    spec = client.get("/v1/openapi.json").json()
    for path in spec["paths"].values():
        for operation in path.values():
            assert "422" not in operation["responses"]
            assert operation["responses"]["default"]["content"]


def test_oversized_bodies_are_rejected(client: TestClient) -> None:
    """QA Q7: bodies over 1 MB never reach a handler."""
    big = b'{"idToken": "' + b"x" * (1024 * 1024) + b'"}'
    declared = client.post(
        "/v1/sessions", content=big, headers={"Content-Type": "application/json"}
    )
    assert (declared.status_code, error_of(declared)["details"][0]["reason"]) == (
        400,
        "REQUEST_TOO_LARGE",
    )

    def chunks() -> Any:
        for _ in range(5):
            yield b"x" * (300 * 1024)

    streamed = client.post(
        "/v1/sessions", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert error_of(streamed)["details"][0]["reason"] == "REQUEST_TOO_LARGE"


def playlist(*tracks: list[str]) -> dict[str, Any]:
    return {
        "tracks": [{"title": f"song {i}", "artists": artists} for i, artists in enumerate(tracks)]
    }


def test_analyze_playlist(client: TestClient) -> None:
    body = playlist(["Bob"], ["Carol", "Bob"], ["the band"], ["Nobody We Know"])
    result = client.post("/v1/playlists:analyze", json=body).json()
    rows = {r["query"]: r for r in result["artists"]}
    assert rows["Bob"]["status"] == "MATCHED"
    assert rows["Bob"]["trackCount"] == 2
    assert rows["the band"]["artist"]["name"] == BAND
    assert rows["Nobody We Know"]["status"] == "NO_MATCH"
    # Bob-Carol are direct (Carol produced Bob's feature); The Band links via Alice.
    assert result["cohesion"] == {"score": 1.0, "pairsWithinTwo": 3, "pairs": 3}
    (connector,) = result["connectors"]
    assert connector["artist"]["name"] == ALICE
    assert sorted(connector["linkedTo"]) == sorted([BOB, CAROL, BAND])
    thread = [a["name"] for a in result["thread"]["artists"]]
    assert thread[0] == BOB
    assert result["thread"]["breaks"] == 0
    assert {(link["artistA"], link["artistB"]) for link in result["links"]} == {
        tuple(sorted((BOB, CAROL)))
    }


def test_analyze_playlist_accepts_explicit_choices(client: TestClient) -> None:
    result = client.post(
        "/v1/playlists:analyze",
        json=playlist([ALICE], ["artists/00000000-0000-0000-0000-000000000000"]),
    ).json()
    statuses = [r["status"] for r in result["artists"]]
    assert statuses == ["MATCHED", "NO_MATCH"]


def test_analyze_playlist_limits(client: TestClient) -> None:
    too_many = playlist(*([f"Artist {i}"] for i in range(2001)))
    response = client.post("/v1/playlists:analyze", json=too_many)
    assert error_of(response)["details"][0]["metadata"]["field"] == "tracks"
    empty = client.post("/v1/playlists:analyze", json=playlist(["   "]))
    assert error_of(empty)["status"] == "INVALID_ARGUMENT"


def test_playlist_contents_never_reach_the_logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Plan §20.3: request bodies are never logged."""
    secret = "Zzyzx Private Listening Name"
    with caplog.at_level("DEBUG"):
        client.post("/v1/playlists:analyze", json=playlist([secret], ["Bob"]))
    assert caplog.records, "expected the request log line"
    assert all(
        secret not in record.getMessage() and secret not in str(record.__dict__)
        for record in caplog.records
    )
