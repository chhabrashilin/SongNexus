"""Genres in the API with Discogs and Wikidata enrichment (R2-1)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from songnexus.catalog.ingest import EnrichmentInputs, ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.core.text import normalize
from songnexus.service.app import build_state, create_app
from songnexus.storage import migrate
from songnexus.storage.db import make_engine
from tests.catalog import fixtures as fx

GENRE_MAP = Path(__file__).resolve().parents[3] / "data" / "seeds" / "discogs_genre_map.json"
ALICE = f"artists/{ids.artist_id('mb-alice')}"
BOB = f"artists/{ids.artist_id('mb-bob')}"
CAROL = f"artists/{ids.artist_id('mb-carol')}"


def genre(name: str) -> str:
    return f"genres/{ids.genre_id(normalize(name))}"


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("genres")
    paths = {}
    for name, records in {
        "mb": [*fx.small_catalog(), fx.genre_list_record()],
        "wikidata": fx.wikidata_records(),
        "discogs": fx.discogs_records(),
    }.items():
        paths[name] = root / f"{name}.jsonl.gz"
        write_snapshot(records, paths[name])
    url = f"sqlite:///{root / 'catalog.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(
        engine, paths["mb"], EnrichmentInputs(paths["wikidata"], paths["discogs"], GENRE_MAP)
    )
    return Settings(database_url=url, data_dir=root, log_json=False, read_model_refresh_s=3600)


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, build_state(settings)))


@pytest.fixture(scope="module")
def client(settings: Settings) -> Iterator[TestClient]:
    with _client(settings) as test_client:
        yield test_client


def _genres(client: TestClient) -> dict[str, dict[str, Any]]:
    body = client.get("/v1/genres", params={"pageSize": 100}).json()
    return {g["displayName"]: g for g in body["genres"]}


def test_list_genres_has_parents_and_counts_through_subgenres(client: TestClient) -> None:
    genres = _genres(client)
    assert genres["trap"]["parents"] == [genre("hip hop")]
    assert genres["Hip-Hop"]["artistCountWithSubgenres"] >= genres["Hip-Hop"]["artistCount"]
    assert genres["jazz"]["artistCountWithSubgenres"] >= genres["bebop"]["artistCount"]


def test_artist_genres_name_their_sources(client: TestClient) -> None:
    artist = client.get(f"/v1/{ALICE}").json()
    by_name = {g["displayName"]: g for g in artist["genres"]}
    assert by_name["jazz"]["sources"] == [
        "dataSources/discogs",
        "dataSources/musicbrainz-supplementary",
    ]
    assert sum(g["share"] for g in artist["genres"]) <= 1.0001


def test_collaborations_accept_a_genre_filter(client: TestClient) -> None:
    def collaborators(**params: Any) -> list[str]:
        body = client.get(
            f"/v1/{ALICE}/collaborations",
            params={"type": "FEATURE", "includeUnknownGenre": False, **params},
        ).json()
        return [c["artist"]["name"] for c in body["collaborations"]]

    assert collaborators() == [BOB]
    assert collaborators(genres=[genre("r&b")]) == [BOB]
    assert collaborators(genres=[genre("hip hop")]) == []


def test_compare_filters_mutual_collaborators_by_genre(client: TestClient) -> None:
    def mutual(**params: Any) -> list[str]:
        body = client.get(
            f"/v1/{BOB}:compare", params={"other": CAROL, "includeUnknownGenre": False, **params}
        ).json()
        return [a["name"] for a in body["mutualCollaborators"]]

    assert mutual() == [ALICE]
    assert mutual(genres=[genre("hip hop")]) == [ALICE]
    # Alice's funk share is under the threshold: she is filtered out as a mutual collaborator.
    assert mutual(genres=[genre("funk")]) == []


def test_an_unknown_genre_is_not_found(client: TestClient) -> None:
    missing = "genres/00000000-0000-0000-0000-000000000000"
    response = client.get(f"/v1/{ALICE}/collaborations", params={"genres": [missing]})
    assert response.status_code == 404
    assert response.json()["error"]["details"][0]["reason"] == "GENRE_NOT_FOUND"


def test_a_commercial_build_serves_discogs_genres_only(settings: Settings) -> None:
    commercial = settings.model_copy(update={"genre_sources": ["discogs"]})
    with _client(commercial) as client:
        alice = client.get(f"/v1/{ALICE}").json()
        bob = client.get(f"/v1/{BOB}").json()
        genres = _genres(client)
    assert {s for g in alice["genres"] for s in g["sources"]} == {"dataSources/discogs"}
    assert [g["displayName"] for g in bob["genres"]] == ["funk", "soul"]  # R&B was MusicBrainz
    assert "R&B" not in genres


def test_unknown_genre_sources_are_rejected_at_startup() -> None:
    with pytest.raises(ValidationError, match="unknown genre sources"):
        Settings(genre_sources=["kaggle-spotify-tracks"])
