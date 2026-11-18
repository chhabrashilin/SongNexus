"""AcousticBrainz: what the snapshot keeps, how descriptors join recordings, and the fetch."""

from pathlib import Path

import httpx
import pytest

from songnexus.catalog import acousticbrainz as ab
from songnexus.catalog.canonicalize import build_batch
from songnexus.catalog.enrich import GenreMap, build_enrichment
from songnexus.catalog.snapshot import read_snapshot
from tests.catalog import fixtures as fx

GENRE_MAP = Path(__file__).resolve().parents[3] / "data" / "seeds" / "discogs_genre_map.json"


def test_the_snapshot_keeps_only_the_fields_used() -> None:
    records = ab.snapshot_records(fx.acousticbrainz_responses())
    assert [r.body["recording"] for r in records] == ["rec-1", "rec-2"]
    first = records[0].body
    assert first["bpm"] == 96.0
    assert (first["key"], first["scale"]) == ("A", "minor")
    assert first["happy"] == pytest.approx(0.7)
    assert first["instrumental"] == pytest.approx(0.1)
    assert first["length_s"] == 201.5
    assert "gender" not in first
    assert "female" not in first


def test_descriptors_join_canonical_recordings() -> None:
    batch = build_batch(fx.small_catalog())
    out = build_enrichment(
        batch,
        [],
        [],
        GenreMap.load(GENRE_MAP),
        acousticbrainz_records=ab.snapshot_records(fx.acousticbrainz_responses()),
    )
    by_mbid = {row["source_recording_id"]: row for row in out.descriptors.values()}
    # rec-1 and its remaster rec-3 are one canonical recording; rec-1 carries the data.
    assert set(by_mbid) == {"rec-1", "rec-2"}
    assert by_mbid["rec-1"]["moods"] == {
        "happy": pytest.approx(0.7),
        "instrumental": pytest.approx(0.1),
    }
    assert {row["source_id"] for row in out.descriptors.values()} == {"acousticbrainz"}


def test_fetch_batches_25_recordings_per_request(tmp_path: Path) -> None:
    seen: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recordings = request.url.params["recording_ids"].split(";")
        seen.append((request.url.path.rsplit("/", 1)[-1], len(recordings)))
        body = {r: {"0": fx.acousticbrainz_low(r, 100.0, "C", "major")} for r in recordings[:2]}
        return httpx.Response(200, json={**body, "mbid_mapping": {}})

    client = ab.AcousticBrainzClient(
        base_url="https://ab.test/api/v1",
        cache_dir=tmp_path / "cache",
        min_interval_s=0,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    stats = ab.run_fetch(
        client, recording_ids=[f"r{i:02}" for i in range(30)], snapshot_path=tmp_path / "ab.gz"
    )
    assert seen == [("low-level", 25), ("high-level", 25), ("low-level", 5), ("high-level", 5)]
    assert stats["withDescriptors"] == 4
    assert len(list(read_snapshot(tmp_path / "ab.gz"))) == 4
