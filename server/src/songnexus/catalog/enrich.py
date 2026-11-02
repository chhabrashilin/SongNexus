"""Enrichment: Discogs genres and the Wikidata genre hierarchy, on top of the MusicBrainz batch.

``build_enrichment`` is pure, like ``build_batch``: raw records in, canonical
rows out. Nothing is matched by name across sources:

* **Artists** join Discogs through IDs: MusicBrainz's own Discogs URL relations
  (confidence 1.0) and Wikidata items carrying both a MusicBrainz artist ID
  (P434) and a Discogs artist ID (P1953) (confidence 0.9). A Discogs ID claimed
  by two catalog artists is ambiguous and dropped.
* **Genres** stay in the MusicBrainz vocabulary. A Discogs genre or style maps
  to a vocabulary genre by normalized name, or through the reviewed table in
  ``data/seeds/discogs_genre_map.json``; anything else is reported, not stored.
* **Genre parents** come from Wikidata ``subclass of`` (P279) between items
  carrying MusicBrainz genre IDs (P8052).

An artist's Discogs genre votes are the number of its distinct masters tagged
with that genre, the same unit (one vote per release) as MusicBrainz tag counts.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from songnexus.catalog.canonicalize import CanonicalBatch, Row
from songnexus.catalog.snapshot import RawRecord
from songnexus.catalog.wikidata.fetch import bindings
from songnexus.core import ids
from songnexus.core.text import normalize

DISCOGS_SOURCE_ID = "discogs"
WIKIDATA_SOURCE_ID = "wikidata"
MUSICBRAINZ_LINK_CONFIDENCE = 1.0
WIKIDATA_LINK_CONFIDENCE = 0.9

_DISCOGS_ARTIST_URL = re.compile(r"discogs\.com/(?:[a-z]{2}/)?artist/(\d+)")


@dataclass(frozen=True)
class GenreMap:
    """The reviewed Discogs-name table (``data/seeds/discogs_genre_map.json``)."""

    mapped: dict[str, tuple[str, ...]]  # normalized Discogs name -> normalized genre names
    not_genres: frozenset[str]  # normalized Discogs names

    @classmethod
    def load(cls, path: Path) -> GenreMap:
        """Reads the table.

        Raises:
            KeyError, ValueError: The file is malformed.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            mapped={normalize(k): tuple(normalize(g) for g in v) for k, v in data["map"].items()},
            not_genres=frozenset(normalize(n) for n in data["notGenres"]),
        )


@dataclass(frozen=True)
class DiscogsLink:
    """How one Discogs artist ID was linked to a catalog artist."""

    artist_id: str
    method: str
    confidence: float


@dataclass
class EnrichmentBatch:
    """Rows contributed by Discogs and Wikidata, keyed by primary key."""

    mappings: dict[str, Row] = field(default_factory=dict)
    artist_genres: dict[tuple[str, str, str], Row] = field(default_factory=dict)
    genre_parents: dict[tuple[str, str, str], Row] = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter)
    unmapped_names: Counter[str] = field(default_factory=Counter)


def _entity_index(batch: CanonicalBatch, entity_type: str) -> dict[str, str]:
    """Returns MusicBrainz ID -> canonical ID for one entity type."""
    return {
        row["source_entity_id"]: row["entity_id"]
        for row in batch.mappings.values()
        if row["entity_type"] == entity_type
    }


def discogs_links(
    batch: CanonicalBatch, wikidata_records: Iterable[RawRecord]
) -> tuple[dict[str, DiscogsLink], int]:
    """Returns Discogs artist ID -> catalog artist, and how many IDs were ambiguous.

    MusicBrainz links win over Wikidata links for the same Discogs ID.
    """
    candidates: dict[str, dict[str, DiscogsLink]] = defaultdict(dict)
    for row in batch.links.values():
        match = _DISCOGS_ARTIST_URL.search(row["url"])
        if row["link_type"] == "discogs" and match:
            candidates[match.group(1)][row["artist_id"]] = DiscogsLink(
                row["artist_id"], "musicbrainz_url", MUSICBRAINZ_LINK_CONFIDENCE
            )
    artists = _entity_index(batch, "artist")
    for record in wikidata_records:
        for row in bindings(record):
            artist_id = artists.get(row.get("musicbrainz", ""))
            discogs_id = row.get("discogs", "")
            if artist_id and discogs_id.isdigit():
                candidates[discogs_id].setdefault(
                    artist_id, DiscogsLink(artist_id, "wikidata_p1953", WIKIDATA_LINK_CONFIDENCE)
                )
    links = {d: next(iter(c.values())) for d, c in candidates.items() if len(c) == 1}
    return links, len(candidates) - len(links)


def _genre_ids_for(
    name: str, vocabulary: dict[str, str], genre_map: GenreMap, out: EnrichmentBatch
) -> tuple[str, ...]:
    norm = normalize(name)
    if norm in vocabulary:
        return (vocabulary[norm],)
    if norm in genre_map.not_genres:
        out.stats["discogs_names_not_genres"] += 1
        return ()
    if norm in genre_map.mapped:
        return tuple(vocabulary[g] for g in genre_map.mapped[norm] if g in vocabulary)
    out.unmapped_names[name] += 1
    return ()


def _add_discogs_genres(
    out: EnrichmentBatch,
    batch: CanonicalBatch,
    links: dict[str, DiscogsLink],
    discogs_records: Iterable[RawRecord],
    genre_map: GenreMap,
) -> None:
    vocabulary = {row["normalized_name"]: genre_id for genre_id, row in batch.genres.items()}
    # Per catalog artist: genre -> distinct masters, and the first raw record asserting it.
    masters_by_genre: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    first_key: dict[tuple[str, str], str] = {}
    for record in sorted(discogs_records, key=lambda r: r.request_key):
        if record.kind != "masters":
            continue
        link = links.get(str(record.body.get("artist", "")))
        if link is None:
            out.stats["discogs_records_unlinked"] += 1
            continue
        for master in record.body.get("masters", []):
            names = [*master.get("genres", []), *master.get("styles", [])]
            for genre_id in {
                g for n in names for g in _genre_ids_for(n, vocabulary, genre_map, out)
            }:
                masters_by_genre[link.artist_id][genre_id].add(str(master["id"]))
                first_key.setdefault((link.artist_id, genre_id), record.request_key)
    for artist_id, genres in masters_by_genre.items():
        for genre_id, masters in genres.items():
            out.artist_genres[(artist_id, genre_id, DISCOGS_SOURCE_ID)] = {
                "artist_id": artist_id,
                "genre_id": genre_id,
                "votes": len(masters),
                "source_id": DISCOGS_SOURCE_ID,
                "_raw_key": first_key[(artist_id, genre_id)],
                "confidence": 1.0,
            }
    out.stats["discogs_artists_with_genres"] = len(masters_by_genre)


def _add_genre_parents(
    out: EnrichmentBatch, batch: CanonicalBatch, wikidata_records: Iterable[RawRecord]
) -> None:
    genres = _entity_index(batch, "genre")
    for record in wikidata_records:
        for row in bindings(record):
            child, parent = genres.get(row.get("genre", "")), genres.get(row.get("parent", ""))
            if child and parent and child != parent:
                out.genre_parents[(child, parent, WIKIDATA_SOURCE_ID)] = {
                    "genre_id": child,
                    "parent_genre_id": parent,
                    "source_id": WIKIDATA_SOURCE_ID,
                    "_raw_key": record.request_key,
                    "confidence": 1.0,
                }


def build_enrichment(
    batch: CanonicalBatch,
    wikidata_records: Iterable[RawRecord],
    discogs_records: Iterable[RawRecord],
    genre_map: GenreMap,
) -> EnrichmentBatch:
    """Builds the Discogs and Wikidata rows for an already-built MusicBrainz batch."""
    wikidata_records, discogs_records = list(wikidata_records), list(discogs_records)
    out = EnrichmentBatch()
    links, ambiguous = discogs_links(batch, wikidata_records)
    out.stats["discogs_ids_ambiguous"] = ambiguous
    for discogs_id, link in sorted(links.items()):
        mapping_id = ids.canonical_id("mapping", f"{DISCOGS_SOURCE_ID}|artist|{discogs_id}")
        out.mappings[mapping_id] = {
            "id": mapping_id,
            "entity_type": "artist",
            "entity_id": link.artist_id,
            "source_id": DISCOGS_SOURCE_ID,
            "source_entity_id": discogs_id,
            "match_method": link.method,
            "confidence": link.confidence,
            "decision": "merged",
        }
    out.stats["discogs_ids_linked"] = len(links)
    out.stats["artists_linked_to_discogs"] = len({link.artist_id for link in links.values()})
    _add_discogs_genres(out, batch, links, discogs_records, genre_map)
    _add_genre_parents(out, batch, wikidata_records)
    out.stats["genre_parent_links"] = len(out.genre_parents)
    return out
