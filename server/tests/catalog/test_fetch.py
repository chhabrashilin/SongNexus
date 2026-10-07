import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from songnexus.catalog.musicbrainz.client import MusicBrainzClient, MusicBrainzError
from songnexus.catalog.musicbrainz.fetch import (
    Seed,
    SeedResolutionError,
    choose_release,
    credited_performers,
    load_seeds,
    resolve_seed,
    select_albums,
)
from songnexus.catalog.musicbrainz.snapshot import read_snapshot, request_key, write_snapshot
from tests.catalog import fixtures as fx


def _client(tmp_path: Path, handler: Any) -> MusicBrainzClient:
    return MusicBrainzClient(
        base_url="https://musicbrainz.test/ws/2",
        cache_dir=tmp_path / "cache",
        min_interval_s=0,
        max_retries=3,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_client_caches_responses(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"id": "x"})

    client = _client(tmp_path, handler)
    first = client.get("artist", "artist/x", {"inc": "aliases"})
    again = _client(tmp_path, handler).get("artist", "artist/x", {"inc": "aliases"})
    assert first == again
    assert len(calls) == 1
    assert "fmt=json" in calls[0]


def test_client_retries_then_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    responses = iter([httpx.Response(503), httpx.Response(200, json={"ok": True})])
    client = _client(tmp_path, lambda _r: next(responses))
    assert client.get("artist", "artist/y", {}).body == {"ok": True}
    assert client.network_requests == 2


def test_client_fails_fast_on_client_errors(tmp_path: Path) -> None:
    client = _client(tmp_path, lambda _r: httpx.Response(404, text="not found"))
    with pytest.raises(MusicBrainzError, match="404"):
        client.get("artist", "artist/z", {})


def test_client_gives_up_after_max_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client = _client(tmp_path, lambda _r: httpx.Response(503))
    with pytest.raises(MusicBrainzError, match="after 3 attempts"):
        client.get("artist", "artist/z", {})


def test_snapshot_round_trip_is_byte_identical(tmp_path: Path) -> None:
    records = fx.small_catalog()
    a, b = tmp_path / "a.gz", tmp_path / "b.gz"
    write_snapshot(records, a)
    write_snapshot(reversed(records), b)
    assert a.read_bytes() == b.read_bytes()
    assert sorted(read_snapshot(a), key=lambda r: r.request_key) == sorted(
        records, key=lambda r: r.request_key
    )


def test_request_key_ignores_fmt_and_param_order() -> None:
    assert request_key("artist", {"b": 1, "a": 2, "fmt": "json"}) == request_key(
        "artist", {"a": 2, "b": 1}
    )


def test_load_seeds_requires_pin_reasons(tmp_path: Path) -> None:
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps({"artists": [{"name": "Drake", "mbid": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="pin_reason"):
        load_seeds(path)


def test_load_seeds_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps({"artists": [{"name": "SZA"}, {"name": "sza"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_seeds(path)


def test_ambiguous_seed_fails_loudly_with_candidates(tmp_path: Path) -> None:
    body = {
        "artists": [
            {"id": "a", "name": "Drake", "score": 100, "disambiguation": "rapper"},
            {"id": "b", "name": "Drake", "score": 100, "disambiguation": "metal band"},
        ]
    }
    client = _client(tmp_path, lambda _r: httpx.Response(200, json=body))
    with pytest.raises(SeedResolutionError, match="ambiguous") as error:
        resolve_seed(client, Seed("Drake"))
    assert "metal band" in str(error.value)


def test_pinned_seed_skips_search(tmp_path: Path) -> None:
    client = _client(tmp_path, lambda _r: pytest.fail("no request expected"))
    assert resolve_seed(client, Seed("Drake", "mbid-1", "reason")).method == "pinned_mbid"


def test_select_albums_prefers_votes_then_date() -> None:
    groups: list[dict[str, Any]] = [
        {
            "id": "1",
            "primary-type": "Album",
            "first-release-date": "2001",
            "rating": {"votes-count": 5},
        },
        {
            "id": "2",
            "primary-type": "Album",
            "first-release-date": "2000",
            "rating": {"votes-count": 9},
        },
        {
            "id": "3",
            "primary-type": "Album",
            "secondary-types": ["Live"],
            "first-release-date": "1999",
        },
        {"id": "4", "primary-type": "Album", "first-release-date": "1998"},
        {"id": "5", "primary-type": "Single", "first-release-date": "1997"},
    ]
    assert [g["id"] for g in select_albums(groups, 3)] == ["2", "1", "4"]


def test_choose_release_avoids_clean_versions() -> None:
    releases: list[dict[str, Any]] = [
        {"id": "clean", "status": "Official", "date": "2010", "disambiguation": "clean"},
        {"id": "deluxe", "status": "Official", "date": "2011", "media": [{"track-count": 20}]},
        {"id": "standard", "status": "Official", "date": "2011", "media": [{"track-count": 12}]},
    ]
    chosen = choose_release(releases)
    assert chosen is not None
    assert chosen["id"] == "standard"


def test_credited_performers_cover_release_and_recording_credits() -> None:
    release = fx.small_catalog()[2]
    assert credited_performers(release.body) == {"mb-alice", "mb-bob"}


def test_corrupt_cache_entries_are_refetched(tmp_path: Path) -> None:
    """QA Q13."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"id": "x"})

    client = _client(tmp_path, handler)
    client.get("artist", "artist/x", {})
    for cached in (tmp_path / "cache").glob("*.json"):
        cached.write_text("{torn", encoding="utf-8")
    assert _client(tmp_path, handler).get("artist", "artist/x", {}).body == {"id": "x"}
    assert len(calls) == 2
