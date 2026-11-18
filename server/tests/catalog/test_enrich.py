"""Enrichment: Discogs genres and Wikidata genre parents on top of the MusicBrainz batch."""

from pathlib import Path

import pytest

from songnexus.catalog.canonicalize import CanonicalBatch, build_batch
from songnexus.catalog.enrich import (
    DISCOGS_SOURCE_ID,
    WIKIDATA_SOURCE_ID,
    GenreMap,
    build_enrichment,
    discogs_links,
)
from songnexus.core import ids
from tests.catalog import fixtures as fx

GENRE_MAP = Path(__file__).resolve().parents[3] / "data" / "seeds" / "discogs_genre_map.json"
ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")


def genre(name: str) -> str:
    return ids.genre_id(name)


@pytest.fixture
def batch() -> CanonicalBatch:
    return build_batch([*fx.small_catalog(), fx.genre_list_record()])


def test_the_genre_list_becomes_the_vocabulary_with_musicbrainz_ids(batch: CanonicalBatch) -> None:
    vocabulary = {
        r["entity_id"]: r["source_entity_id"]
        for r in batch.mappings.values()
        if r["entity_type"] == "genre"
    }
    assert vocabulary[genre("trap")] == "g-trap"
    assert batch.genres[genre("trap")]["name"] == "trap"
    assert len(vocabulary) == len(fx.GENRE_MBIDS)


def test_discogs_links_prefer_musicbrainz_and_drop_ambiguous_ids(batch: CanonicalBatch) -> None:
    batch.links["x"] = {
        "id": "x",
        "artist_id": BOB,
        "link_type": "discogs",
        "url": "https://www.discogs.com/artist/201-Bob",
        "source_id": "musicbrainz",
        "_raw_key": "artist/mb-bob?inc=artist_profile",
    }
    clash = fx.sparql_record("clash", [{"musicbrainz": "mb-alice", "discogs": "201"}])
    links, ambiguous = discogs_links(batch, [*fx.wikidata_records(), clash])
    assert links["101"].artist_id == ALICE
    assert links["101"].method == "wikidata_p1953"
    assert links["101"].confidence == 0.9
    assert "201" not in links  # claimed by Bob (MusicBrainz) and Alice (Wikidata)
    assert ambiguous == 1


def test_discogs_genres_count_distinct_masters_across_profiles(batch: CanonicalBatch) -> None:
    out = build_enrichment(
        batch, fx.wikidata_records(), fx.discogs_records(), GenreMap.load(GENRE_MAP)
    )
    votes = {(a, g): r["votes"] for (a, g, _s), r in out.artist_genres.items()}
    # Masters 1 and 3 are hip hop; master 2 appears under both profiles but counts once.
    assert votes[(ALICE, genre("hip hop"))] == 2
    assert votes[(ALICE, genre("jazz"))] == 1
    assert votes[(ALICE, genre("trap"))] == 1
    # Reviewed table: "Bop" -> bebop, "Funk / Soul" -> funk and soul.
    assert votes[(ALICE, genre("bebop"))] == 1
    assert votes[(ALICE, genre("funk"))] == votes[(ALICE, genre("soul"))] == 1
    assert votes[(BOB, genre("soul"))] == 1
    assert {r["source_id"] for r in out.artist_genres.values()} == {DISCOGS_SOURCE_ID}


def test_names_outside_the_vocabulary_are_reported_not_stored(batch: CanonicalBatch) -> None:
    out = build_enrichment(
        batch, fx.wikidata_records(), fx.discogs_records(), GenreMap.load(GENRE_MAP)
    )
    assert out.unmapped_names == {"Contemporary Weirdness": 1}
    assert out.stats["discogs_names_not_genres"] == 1  # "Soundtrack"
    stored = {g for (_a, g, _s) in out.artist_genres}
    assert stored <= set(batch.genres)


def test_genre_parents_join_by_musicbrainz_genre_id(batch: CanonicalBatch) -> None:
    out = build_enrichment(batch, fx.wikidata_records(), [], GenreMap.load(GENRE_MAP))
    parents = {(c, p) for (c, p, _s) in out.genre_parents}
    assert parents == {(genre("trap"), genre("hip hop")), (genre("bebop"), genre("jazz"))}
    assert {r["source_id"] for r in out.genre_parents.values()} == {WIKIDATA_SOURCE_ID}


def test_enrichment_is_deterministic(batch: CanonicalBatch) -> None:
    genre_map = GenreMap.load(GENRE_MAP)
    first = build_enrichment(batch, fx.wikidata_records(), fx.discogs_records(), genre_map)
    again = build_enrichment(
        batch, reversed(fx.wikidata_records()), reversed(fx.discogs_records()), genre_map
    )
    assert first.artist_genres == again.artist_genres
    assert first.genre_parents == again.genre_parents
    assert first.mappings == again.mappings
