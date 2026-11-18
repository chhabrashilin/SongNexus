"""Listener overlap in Compare and "often played with" on artist pages (R2-5)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    root = tmp_path_factory.mktemp("listening")
    paths = {}
    for name, records in {
        "mb": fx.small_catalog(),
        "empty": [],
        "listenbrainz": fx.listenbrainz_records(),
    }.items():
        paths[name] = root / f"{name}.jsonl.gz"
        write_snapshot(records, paths[name])
    url = f"sqlite:///{root / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(
        engine,
        paths["mb"],
        EnrichmentInputs(
            paths["empty"],
            paths["empty"],
            GENRE_MAP,
            listenbrainz_snapshot=paths["listenbrainz"],
        ),
    )
    settings = Settings(database_url=url, data_dir=root, log_json=False, read_model_refresh_s=3600)
    with TestClient(create_app(settings, build_state(settings))) as test_client:
        yield test_client


def test_compare_reports_listener_overlap_with_its_counts(client: TestClient) -> None:
    body = client.get(f"/v1/{ALICE}:compare", params={"other": BOB}).json()
    listening = body["listening"]
    assert listening["listenersA"] == 5000
    assert listening["listenersB"] == 800
    assert listening["rankBForA"] == 3
    assert listening["rankAForB"] == 1
    assert listening["strength"] == "STRONG"
    assert listening["source"]["source"] == "dataSources/listenbrainz"


def test_small_audiences_are_never_described(client: TestClient) -> None:
    body = client.get(f"/v1/{ALICE}:compare", params={"other": CAROL}).json()
    assert body["listening"] is None


def test_artist_pages_list_who_is_often_played_with_them(client: TestClient) -> None:
    alice = client.get(f"/v1/{ALICE}").json()
    assert [(c["artist"]["name"], c["rank"]) for c in alice["oftenPlayedWith"]] == [
        (BOB, 3),
        (CAROL, 60),
    ]


def test_artist_summaries_carry_public_listener_counts_above_the_floor(
    client: TestClient,
) -> None:
    summaries = {
        c["artist"]["name"]: c["artist"]["listeners"]
        for c in client.get(f"/v1/{ALICE}/connections").json()["connections"]
    }
    assert summaries[BOB] == 800
    # Carol has 12 listeners: under the floor, so not described at all.
    assert summaries[CAROL] is None
    assert client.get(f"/v1/{ALICE}").json()["listeners"] == 5000


def test_relevance_order_is_the_same_set_as_strength_order(client: TestClient) -> None:
    def names(order: str) -> list[str]:
        body = client.get(f"/v1/{ALICE}/connections", params={"orderBy": order}).json()
        return [c["artist"]["name"] for c in body["connections"]]

    by_strength, by_relevance = names("strength desc"), names("relevance desc")
    assert sorted(by_strength) == sorted(by_relevance)
    # Bob has public listeners and Carol does not: Bob comes first when relevance decides.
    if BOB in by_relevance and CAROL in by_relevance:
        assert by_relevance.index(BOB) < by_relevance.index(CAROL)


def test_unknown_order_is_rejected_with_the_options(client: TestClient) -> None:
    response = client.get(f"/v1/{ALICE}/connections", params={"orderBy": "popularity"})
    assert response.status_code == 400
    assert "relevance desc" in response.json()["error"]["message"]
