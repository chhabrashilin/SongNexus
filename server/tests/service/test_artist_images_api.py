"""Artist photos in the API: summaries carry the thumbnail, GetArtist the attribution."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.service.app import build_state, create_app
from songnexus.service.readmodel import probe_version
from songnexus.storage import migrate
from songnexus.storage.artist_images import ImageRecord, write_images
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx

ALICE_ID = ids.artist_id("mb-alice")
ALICE = f"artists/{ALICE_ID}"
BOB = f"artists/{ids.artist_id('mb-bob')}"
THUMB = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/aa/Alice.jpg/330px-Alice.jpg"
LARGE = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/aa/Alice.jpg/960px-Alice.jpg"
RECORD = ImageRecord(
    wikidata_id="Q1",
    commons_file="File:Alice.jpg",
    thumbnail_url=THUMB,
    large_url=LARGE,
    width=2000,
    height=3000,
    page_url="https://commons.wikimedia.org/wiki/File:Alice.jpg",
    author="Jane Photographer",
    license="CC BY-SA 4.0",
    license_url="https://creativecommons.org/licenses/by-sa/4.0",
    attribution_required=True,
)


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("images-api")
    snapshot = root / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    url = f"sqlite:///{root / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    before = probe_version(engine)
    with session_scope(engine) as session:
        write_images(session, {ALICE_ID: RECORD}, datetime(2026, 11, 16, tzinfo=UTC))
    after = probe_version(engine)
    # Photos change the served version, and so every cache key and ETag.
    assert before is not None
    assert after is not None
    assert after == f"{before}.img{after.rsplit('.img', 1)[-1]}"
    assert after != before
    engine.dispose()
    return Settings(
        database_url=url, data_dir=Path(root), log_json=False, read_model_refresh_s=3600
    )


@pytest.fixture(scope="module")
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, build_state(settings))) as test_client:
        yield test_client


def test_get_artist_has_the_photo_with_attribution(client: TestClient) -> None:
    body = client.get(f"/v1/{ALICE}").json()
    assert body["imageUrl"] == THUMB
    assert body["image"] == {
        "url": LARGE,
        "thumbnailUrl": THUMB,
        "width": 2000,
        "height": 3000,
        "pageUrl": "https://commons.wikimedia.org/wiki/File:Alice.jpg",
        "author": "Jane Photographer",
        "license": "CC BY-SA 4.0",
        "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0",
    }
    assert ".img" in body["graphVersion"]


def test_artists_without_a_photo_say_null(client: TestClient) -> None:
    body = client.get(f"/v1/{BOB}").json()
    assert body["imageUrl"] is None
    assert body["image"] is None


def test_summaries_everywhere_carry_the_thumbnail(client: TestClient) -> None:
    connections = client.get(f"/v1/{BOB}/connections").json()["connections"]
    alice = next(c["artist"] for c in connections if c["artist"]["name"] == ALICE)
    assert alice["imageUrl"] == THUMB
    assert "image" not in alice  # attribution detail is on GetArtist only

    results = client.get("/v1/catalog:search", params={"query": "Alice"}).json()["results"]
    hit = next(r for r in results if r["name"] == ALICE)
    assert hit["imageUrl"] == THUMB
    assert all(r["imageUrl"] is None for r in results if r["entityType"] != "ARTIST")


def test_etags_still_answer_304(client: TestClient) -> None:
    first = client.get(f"/v1/{ALICE}")
    etag = first.headers["etag"]
    again = client.get(f"/v1/{ALICE}", headers={"If-None-Match": etag})
    assert again.status_code == 304
