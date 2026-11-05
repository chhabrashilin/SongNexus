"""Song pages and song comparison with AcousticBrainz descriptors (R2-4)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songnexus.catalog import acousticbrainz as ab
from songnexus.catalog.canonicalize import build_batch
from songnexus.catalog.ingest import EnrichmentInputs, ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.service.app import build_state, create_app
from songnexus.storage import migrate
from songnexus.storage.db import make_engine
from tests.catalog import fixtures as fx

GENRE_MAP = Path(__file__).resolve().parents[3] / "data" / "seeds" / "discogs_genre_map.json"
ALICE = f"artists/{ids.artist_id('mb-alice')}"
BOB = f"artists/{ids.artist_id('mb-bob')}"
CAROL = f"artists/{ids.artist_id('mb-carol')}"


def _recording(mbid: str) -> str:
    batch = build_batch(fx.small_catalog())
    (row,) = (
        r
        for r in batch.mappings.values()
        if r["entity_type"] == "recording" and r["source_entity_id"] == mbid
    )
    return f"recordings/{row['entity_id']}"


SONG, OTHER_SONG = _recording("rec-1"), _recording("rec-2")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    root = tmp_path_factory.mktemp("songs")
    paths = {}
    for name, records in {
        "mb": fx.small_catalog(),
        "wikidata": [],
        "discogs": [],
        "acousticbrainz": ab.snapshot_records(fx.acousticbrainz_responses()),
    }.items():
        paths[name] = root / f"{name}.jsonl.gz"
        write_snapshot(records, paths[name])
    url = f"sqlite:///{root / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(
        engine,
        paths["mb"],
        EnrichmentInputs(paths["wikidata"], paths["discogs"], GENRE_MAP, paths["acousticbrainz"]),
    )
    settings = Settings(database_url=url, data_dir=root, log_json=False, read_model_refresh_s=3600)
    with TestClient(create_app(settings, build_state(settings))) as test_client:
        yield test_client


def test_a_song_page_shows_its_audio_descriptors(client: TestClient) -> None:
    song = client.get(f"/v1/{SONG}").json()
    descriptors = song["descriptors"]
    assert descriptors["bpm"] == 96.0
    assert (descriptors["key"], descriptors["scale"]) == ("A", "minor")
    assert descriptors["moods"] == {"happy": 0.7, "instrumental": 0.1}
    assert descriptors["source"]["url"].startswith("https://acousticbrainz.org/")


def test_compare_explains_the_similarity_and_shares_credits(client: TestClient) -> None:
    response = client.get(f"/v1/{SONG}:compare", params={"other": OTHER_SONG})
    assert response.status_code == 200, response.text
    body = response.json()
    parts = {p["name"]: p for p in body["parts"]}
    # 96 and 192.5 BPM are half and double time; A minor is the relative of C major.
    assert parts["tempo"]["similarity"] > 0.95
    assert parts["key"]["similarity"] == 1.0
    assert set(parts) == {"mood", "tempo", "key", "energy"}
    assert sum(p["weight"] for p in body["parts"]) == pytest.approx(1.0, abs=1e-3)
    assert body["similarity"] == pytest.approx(
        sum(p["contribution"] for p in body["parts"]), abs=1e-3
    )
    primary = next(row for row in body["sharedCredits"] if row["role"] == "primary")
    assert [a["name"] for a in primary["both"]] == [ALICE]
    assert body["recordingA"]["artists"][0]["name"] == ALICE
    assert body["artistPath"] == []  # same primary artist


def test_compare_without_data_has_no_score(client: TestClient) -> None:
    body = client.get(f"/v1/{SONG}:compare", params={"other": SONG}).json()
    assert body["similarity"] is not None  # a song is identical to itself
    missing = client.get(
        f"/v1/{SONG}:compare", params={"other": "recordings/00000000-0000-0000-0000-000000000000"}
    )
    assert missing.status_code == 404
