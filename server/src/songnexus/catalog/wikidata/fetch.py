"""Fetch the Wikidata facts SongNexus uses and write them as a snapshot.

Queries go to the public SPARQL endpoint, one at a time with a pause between
them, with an identifying User-Agent as the Wikimedia User-Agent policy asks.
Responses are cached like every other source, so a re-run is free.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from songnexus.catalog.http import PoliteClient, SourceRequestError
from songnexus.catalog.snapshot import RawRecord, write_snapshot

log = logging.getLogger(__name__)

# MusicBrainz IDs per artist-link query; keeps each query well under the endpoint's limits.
ARTIST_BATCH = 400

GENRE_HIERARCHY_QUERY = """\
SELECT ?item ?genre ?parent WHERE {
  ?item wdt:P8052 ?genre .
  OPTIONAL { ?item wdt:P279 ?parentItem . ?parentItem wdt:P8052 ?parent . }
}"""


class WikidataError(SourceRequestError):
    """A Wikidata request failed permanently."""


class WikidataClient(PoliteClient):
    """Runs SPARQL queries against the Wikidata Query Service."""

    error_type = WikidataError

    def __init__(
        self,
        *,
        sparql_url: str,
        cache_dir: Path,
        contact: str = "",
        min_interval_s: float = 1.0,
        http: httpx.Client | None = None,
    ) -> None:
        """Creates a client for the SPARQL endpoint at ``sparql_url``."""
        super().__init__(
            source="wikidata",
            base_url=sparql_url,
            cache_dir=cache_dir,
            contact=contact,
            min_interval_s=min_interval_s,
            accept="application/sparql-results+json",
            http=http,
        )

    def sparql(self, query: str) -> RawRecord:
        """Returns the response to one SPARQL query (POSTed, as long queries require)."""
        return self.post_form("sparql", "", {"query": query, "format": "json"})


def artist_links_query(musicbrainz_ids: Iterable[str]) -> str:
    """Returns the query for Discogs IDs of the given MusicBrainz artist IDs."""
    values = " ".join(f'"{mbid}"' for mbid in sorted(musicbrainz_ids))
    return (
        "SELECT ?item ?musicbrainz ?discogs WHERE {\n"
        f"  VALUES ?musicbrainz {{ {values} }}\n"
        "  ?item wdt:P434 ?musicbrainz ; wdt:P1953 ?discogs .\n"
        "}"
    )


def bindings(record: RawRecord) -> list[dict[str, str]]:
    """Returns a SPARQL response's rows as {variable: value}."""
    rows: list[dict[str, Any]] = record.body.get("results", {}).get("bindings", [])
    return [{k: str(v.get("value", "")) for k, v in row.items()} for row in rows]


def run_fetch(
    client: WikidataClient, *, musicbrainz_artist_ids: Iterable[str], snapshot_path: Path
) -> dict[str, Any]:
    """Fetches artist links and the genre hierarchy, and writes the snapshot.

    Raises:
        WikidataError: A query failed permanently.
    """
    mbids = sorted(set(musicbrainz_artist_ids))
    linked: set[str] = set()
    for start in range(0, len(mbids), ARTIST_BATCH):
        record = client.sparql(artist_links_query(mbids[start : start + ARTIST_BATCH]))
        linked |= {row["musicbrainz"] for row in bindings(record)}
    hierarchy = bindings(client.sparql(GENRE_HIERARCHY_QUERY))
    written = write_snapshot(client.session_records.values(), snapshot_path)
    stats = {
        "artists": len(mbids),
        "artistsWithDiscogs": len(linked),
        "genres": len({row["genre"] for row in hierarchy}),
        "genreParentLinks": len({(r["genre"], r["parent"]) for r in hierarchy if "parent" in r}),
        "records": written,
        "networkRequests": client.network_requests,
        "cacheHits": client.cache_hits,
    }
    log.info("wikidata fetch finished", extra=stats)
    return stats
