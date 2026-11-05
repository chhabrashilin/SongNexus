"""ListenBrainz: what the snapshot keeps, the fetch, and the offline agreement check."""

import json
from pathlib import Path
from typing import Any

import httpx

from songnexus.catalog import listenbrainz as lb
from songnexus.catalog.listening_eval import listener_sets, listening_agreement
from songnexus.catalog.snapshot import RawRecord


def _response(kind: str, body: dict[str, Any]) -> RawRecord:
    return RawRecord(kind, f"{kind}?x", "https://lb.test", "2026-11-04T00:00:00+00:00", body)


def test_the_snapshot_keeps_counts_and_catalog_colisteners_only() -> None:
    popularity = _response(
        "popularity",
        {
            "items": [
                {"artist_mbid": "a", "total_user_count": 120, "total_listen_count": 9000},
                {"artist_mbid": "zzz", "total_user_count": 5, "total_listen_count": 6},
            ]
        },
    )
    similar = _response(
        "similar_artists",
        {
            "items": [
                {"artist_mbid": "outside", "score": 99, "name": "Elsewhere", "gender": "Male"},
                {"artist_mbid": "b", "score": 40, "name": "B", "gender": "Female"},
            ]
        },
    )
    (record_a,) = lb.snapshot_records([popularity], {"a": similar}, {"a", "b"})
    assert record_a.body == {
        "artist": "a",
        "listeners": 120,
        "listens": 9000,
        "algorithm": lb.SIMILARITY_ALGORITHM,
        # Ranks count every similar artist, even those outside the catalog.
        "similar": [{"artist": "b", "score": 40, "rank": 2}],
    }
    assert "gender" not in str(record_a.body)


def test_fetch_posts_popularity_in_batches(tmp_path: Path) -> None:
    batches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            mbids = json.loads(request.content)["artist_mbids"]
            batches.append(len(mbids))
            return httpx.Response(
                200,
                json=[
                    {"artist_mbid": m, "total_user_count": 60, "total_listen_count": 70}
                    for m in mbids
                ],
            )
        return httpx.Response(200, json=[])

    def client(url: str) -> lb.ListenBrainzClient:
        return lb.ListenBrainzClient(
            base_url=url,
            cache_dir=tmp_path / "cache",
            min_interval_s=0,
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    stats = lb.run_fetch(
        client("https://api.lb.test"),
        client("https://labs.lb.test"),
        artist_ids=[f"a{i:03}" for i in range(150)],
        similar_for=["a000"],
        snapshot_path=tmp_path / "lb.gz",
    )
    assert batches == [100, 50]
    assert stats["withCounts"] == 150


def test_agreement_is_high_when_listed_pairs_share_listeners() -> None:
    rows = [(f"u{u}", a) for u in range(10) for a in ("a", "b")]  # a and b share everyone
    rows += [(f"v{u}", a) for u in range(10) for a in ("c",)]
    rows += [(f"w{u}", a) for u in range(10) for a in ("d",)]
    listeners = listener_sets(rows, {"a", "b", "c", "d"})
    report = listening_agreement({"a": ["b"]}, listeners, negatives_per_positive=3, seed=1)
    assert report.positive_pairs == 1
    assert report.auc == 1.0
    assert report.median_jaccard_positive == 1.0
