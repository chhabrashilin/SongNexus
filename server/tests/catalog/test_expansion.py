"""Expansion safety: no lost snapshot records, demo provenance and database overwrite refusal."""

from pathlib import Path

import httpx
import pytest
from sqlalchemy import insert, inspect, select

from songnexus.catalog.canonicalize import build_batch
from songnexus.catalog.communities import load_directory
from songnexus.catalog.merge import merge_snapshots
from songnexus.catalog.musicbrainz.client import MusicBrainzClient
from songnexus.catalog.musicbrainz.recordings import fetch_recordings
from songnexus.catalog.snapshot import RawRecord, read_snapshot, write_snapshot
from songnexus.storage import migrate
from songnexus.storage.db import make_engine
from songnexus.storage.models import DataSource
from songnexus.storage.transfer import transfer


def test_recording_browse_preserves_primary_credit_and_provenance(tmp_path: Path) -> None:
    artist = "83d91898-7763-47d7-b03b-b92132375c47"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["artist"] == artist
        return httpx.Response(
            200,
            json={
                "recording-count": 1,
                "recordings": [
                    {
                        "id": "recording-a",
                        "title": "A single",
                        "artist-credit": [
                            {"name": "Artist", "artist": {"id": artist, "name": "Artist"}}
                        ],
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = MusicBrainzClient(
            base_url="https://musicbrainz.org/ws/2", cache_dir=tmp_path / "cache", http=http
        )
        output = tmp_path / "recordings.gz"
        assert fetch_recordings(client, artist, output, limit=1)["recordings"] == 1
        records = list(read_snapshot(output))
        assert "artist=" in records[0].url
        batch = build_batch(records)
        assert not batch.rejected
        assert len(batch.recordings) == 1
        assert next(iter(batch.recording_credits.values()))["role"] == "primary"


def test_demo_directory_is_searchable_and_never_claims_official_provenance() -> None:
    directory = load_directory()
    demo = [c for c in directory.communities if c.synthetic]
    assert len(demo) == 120
    assert len({c.country for c in demo}) == 40
    assert all(not c.wikidata and not c.website and c.id.startswith("demo-") for c in demo)
    assert any(c.synthetic for c in directory.search("sakura JP"))
    assert len(directory.by_id) == len(directory.communities)


def test_merge_preserves_old_entities_and_updates_conflicts(tmp_path: Path) -> None:
    old = RawRecord(
        "artist", "a", "https://musicbrainz.org/artist/a", "2026-01-01", {"name": "old"}
    )
    new = RawRecord("artist", "a", old.url, "2026-02-01", {"name": "new"})
    other = RawRecord("artist", "b", old.url, old.retrieved_at, {"name": "other"})
    first, second, output = (tmp_path / n for n in ("a.gz", "b.gz", "out.gz"))
    write_snapshot([old, other], first)
    write_snapshot([new], second)
    result = merge_snapshots([first, second], output)
    assert result == {"records": 2, "replaced": 1, "inputs": 2}
    assert [r.body["name"] for r in read_snapshot(output)] == ["new", "other"]
    with pytest.raises(ValueError, match="new output"):
        merge_snapshots([first, second], output)


def test_transfer_dry_run_copy_and_nonempty_refusal(tmp_path: Path) -> None:
    source = make_engine(f"sqlite:///{tmp_path / 'source.sqlite'}")
    target = make_engine(f"sqlite:///{tmp_path / 'target.sqlite'}")
    try:
        migrate.upgrade(source)
        with source.begin() as connection:
            connection.execute(
                insert(DataSource),
                [{"id": "test", "name": "Test", "homepage": "", "license": "CC0"}],
            )
        assert transfer(source, target)["rows"] == 1
        assert not inspect(target).get_table_names()
        assert transfer(source, target, apply=True)["verified"]
        with target.connect() as connection:
            assert connection.scalar(select(DataSource.name)) == "Test"
        with pytest.raises(ValueError, match="not empty"):
            transfer(source, target, apply=True)
        with pytest.raises(ValueError, match="different"):
            transfer(source, source)
    finally:
        source.dispose()
        target.dispose()
