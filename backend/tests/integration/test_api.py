"""HTTP contract tests (FastAPI TestClient over the synthetic dataset)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from songnexus.api.app import create_app
from songnexus.core.config import Settings
from songnexus.core.ids import artist_id_for_mbid
from tests.fixtures import mbid

ALPHA = artist_id_for_mbid(mbid("alpha"))
BETA = artist_id_for_mbid(mbid("beta"))
EPSILON = artist_id_for_mbid(mbid("epsilon"))
THETA = artist_id_for_mbid(mbid("theta"))


def test_health_reports_graph_version_and_rows(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["graph_version"].startswith("run-")
    assert body["rows"]["artists"] == 8
    assert body["llm_available"] is False


def test_search_by_alias_and_typo(client: TestClient) -> None:
    alias = client.get("/api/v1/search", params={"q": "A-Rap"}).json()["results"][0]
    assert alias["id"] == ALPHA and alias["matched_on"] == "A-Rap"
    typo = client.get("/api/v1/search", params={"q": "alpah rapper", "types": "artist"}).json()["results"][0]
    assert typo["name"] == "Alpha Rapper"


def test_artist_detail_includes_provenance_links(client: TestClient) -> None:
    body = client.get(f"/api/v1/artists/{ALPHA}").json()
    assert body["name"] == "Alpha Rapper"
    assert body["genres"][0]["name"] == "hip hop"
    assert body["source_urls"] == [f"https://musicbrainz.org/artist/{mbid('alpha')}"]
    assert {a["title"] for a in body["albums"]} == {"First Light", "First Light (Deluxe)"}


def test_neighbors_payload_shape(client: TestClient) -> None:
    body = client.get(f"/api/v1/artists/{ALPHA}/neighbors", params={"categories": "performance,production"}).json()
    assert body["center"] == ALPHA
    assert {n["name"] for n in body["nodes"]} == {"Alpha Rapper", "Beta Singer", "Delta Producer"}
    assert all(set(e) == {"source", "target", "strength", "kinds"} for e in body["edges"])


def test_path_endpoint(client: TestClient) -> None:
    body = client.get("/api/v1/graph/path", params={"source": BETA, "target": EPSILON, "alternatives": 1}).json()
    assert body["found"] and body["path"]["length"] == 3
    assert len(body["alternatives"]) == 1
    assert body["path"]["hops"][0]["evidence"][0]["sentence"]
    missing = client.get("/api/v1/graph/path", params={"source": ALPHA, "target": THETA}).json()
    assert missing["found"] is False and missing["path"] is None


def test_track_detail_lists_credits_with_roles(client: TestClient) -> None:
    track_id = client.get("/api/v1/search", params={"q": "skyline", "types": "track"}).json()["results"][0]["id"]
    body = client.get(f"/api/v1/tracks/{track_id}").json()
    roles = {(c["artist_name"], c["role"]) for c in body["credits"]}
    assert ("Alpha Rapper", "primary") in roles and ("Beta Singer", "featured") in roles
    assert len(body["source_urls"]) == 2  # original + merged remaster recording


def test_provenance_endpoints(client: TestClient) -> None:
    facts = client.get("/api/v1/provenance/edge", params={"a": ALPHA, "b": BETA}).json()["facts"]
    assert facts and all(f["source"] == "MusicBrainz" and f["raw_record_url"] for f in facts)
    entity = client.get(f"/api/v1/provenance/artist/{ALPHA}").json()
    assert entity["mappings"][0]["match_method"] == "musicbrainz_id"


def test_centrality_and_stats(client: TestClient) -> None:
    ranking = client.get("/api/v1/graph/centrality", params={"metric": "degree", "scope": "all", "limit": 2}).json()
    assert ranking["results"][0]["name"] == "Delta Producer"
    stats = client.get("/api/v1/graph/stats").json()
    assert stats["artists"] == 8 and stats["components"] >= 2


def test_error_envelope_and_request_id(client: TestClient) -> None:
    invalid = client.get(
        "/api/v1/graph/path", params={"source": "nope", "target": ALPHA}, headers={"X-Request-ID": "trace-123"}
    )
    assert invalid.status_code == 422
    assert invalid.headers["X-Request-ID"] == "trace-123"
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["request_id"] == "trace-123"
    missing = client.get("/api/v1/artists/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    bad_category = client.get(f"/api/v1/artists/{ALPHA}/neighbors", params={"categories": "gossip"})
    assert bad_category.status_code == 400


def test_agent_endpoint_deterministic(client: TestClient) -> None:
    body = client.post(
        "/api/v1/agent/query", json={"question": "How is Beta Singer connected to Epsilon Drummer?"}
    ).json()
    assert body["mode_used"] == "deterministic" and body["answer_source"] == "template"
    assert body["path"]["length"] == 3
    assert [t["tool"] for t in body["tools_used"]][:3] == ["search_entities", "search_entities", "find_path"]
    assert body["grounding"]["verified"] and body["grounding"]["path_verified"]
    assert client.post("/api/v1/agent/query", json={"question": ""}).status_code == 422


def test_agent_llm_mode_without_key_falls_back_and_says_so(client: TestClient) -> None:
    body = client.post("/api/v1/agent/query", json={"question": "Tell me about Alpha Rapper", "mode": "llm"}).json()
    assert body["mode_used"] == "deterministic"
    assert any("not configured" in lim for lim in body["limitations"])


def test_agent_rate_limit(loaded_engine: Engine) -> None:
    settings = Settings(database_url="sqlite://", log_json=False, warm_analytics=False, agent_rate_limit_per_minute=1)
    with TestClient(create_app(settings=settings, engine=loaded_engine, llm_client=None)) as c:
        assert c.post("/api/v1/agent/query", json={"question": "Tell me about Alpha Rapper"}).status_code == 200
        limited = c.post("/api/v1/agent/query", json={"question": "Tell me about Alpha Rapper"})
        assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"


def test_reload_requires_admin_token(client: TestClient) -> None:
    assert client.post("/api/v1/system/reload").status_code == 404
    assert client.post("/api/v1/system/reload", headers={"X-Admin-Token": "wrong"}).status_code == 404
    assert client.post("/api/v1/system/reload", headers={"X-Admin-Token": "test-admin-token"}).status_code == 200


def test_metrics_endpoint_records_requests(client: TestClient) -> None:
    client.get("/api/v1/search", params={"q": "zzzzqqqq"})
    body = client.get("/api/v1/system/metrics").json()
    assert body["counters"]["search.empty_results"] == 1
    assert "http.GET /api/v1/search" in body["latency_ms"]
