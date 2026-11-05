"""ListenBrainz adapter (https://listenbrainz.org, listens CC0): listener counts and co-listening.

Two public, key-free endpoints, both keyed by MusicBrainz artist IDs:

* ``POST /1/popularity/artist``: per artist, how many ListenBrainz users listened
  and how many listens (all time).
* Labs ``similar-artists``: per artist, the artists most often played in the same
  listening sessions, with a session co-occurrence score (algorithm named below).

The snapshot keeps, per catalog artist, the two counts and the similar artists
that are themselves in the catalog (ID, score, rank). Names and the gender field
the labs endpoint returns are not kept. Counts are aggregates over all users; no
user names or listens are fetched.
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

POPULARITY_BATCH = 100
# The session-based similarity ListenBrainz serves on its artist pages: 7,500 days
# of listens, 300-second sessions, top 100 per artist.
SIMILARITY_ALGORITHM = (
    "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
)


class ListenBrainzError(SourceRequestError):
    """A ListenBrainz request failed permanently."""


class ListenBrainzClient(PoliteClient):
    """One ListenBrainz host (the API or Labs)."""

    error_type = ListenBrainzError

    def __init__(
        self,
        *,
        base_url: str,
        cache_dir: Path,
        contact: str = "",
        min_interval_s: float = 1.0,
        http: httpx.Client | None = None,
    ) -> None:
        """Creates a client for ``base_url``."""
        super().__init__(
            source="listenbrainz",
            base_url=base_url,
            cache_dir=cache_dir,
            contact=contact,
            min_interval_s=min_interval_s,
            http=http,
        )


def snapshot_records(
    popularity: Iterable[RawRecord], similar: dict[str, RawRecord], catalog: set[str]
) -> list[RawRecord]:
    """Returns one record per catalog artist with listening data.

    Args:
        popularity: Popularity responses (``{"items": [...]}``).
        similar: Artist MBID -> its similar-artists response.
        catalog: MusicBrainz IDs of catalog artists (co-listeners outside it are dropped).
    """
    counts: dict[str, tuple[int, int, str]] = {}
    for response in popularity:
        for item in response.body.get("items", []):
            mbid = item.get("artist_mbid")
            users, listens = item.get("total_user_count"), item.get("total_listen_count")
            if mbid in catalog and isinstance(users, int) and isinstance(listens, int):
                counts[mbid] = (users, listens, response.retrieved_at)
    records = []
    for mbid in sorted(set(counts) | set(similar)):
        body: dict[str, Any] = {"artist": mbid}
        retrieved_at = ""
        if mbid in counts:
            body["listeners"], body["listens"], retrieved_at = counts[mbid]
        if mbid in similar:
            response = similar[mbid]
            retrieved_at = retrieved_at or response.retrieved_at
            ranked = [
                row
                for row in response.body.get("items", [])
                if isinstance(row, dict) and isinstance(row.get("score"), int | float)
            ]
            body["algorithm"] = SIMILARITY_ALGORITHM
            body["similar"] = [
                {"artist": row["artist_mbid"], "score": row["score"], "rank": rank}
                for rank, row in enumerate(ranked, start=1)
                if row.get("artist_mbid") in catalog and row["artist_mbid"] != mbid
            ]
        records.append(
            RawRecord(
                kind="listening",
                request_key=f"artist/{mbid}",
                url=f"https://listenbrainz.org/artist/{mbid}/",
                retrieved_at=retrieved_at,
                body=body,
            )
        )
    return records


def run_fetch(
    api: ListenBrainzClient,
    labs: ListenBrainzClient,
    *,
    artist_ids: Iterable[str],
    similar_for: Iterable[str],
    snapshot_path: Path,
) -> dict[str, Any]:
    """Fetches counts for every artist and co-listening for ``similar_for``; writes the snapshot.

    Raises:
        ListenBrainzError: A request failed permanently.
    """
    catalog = sorted(set(artist_ids))
    popularity = [
        api.post_json(
            "popularity",
            "1/popularity/artist",
            {"artist_mbids": catalog[start : start + POPULARITY_BATCH]},
        )
        for start in range(0, len(catalog), POPULARITY_BATCH)
    ]
    similar = {
        mbid: labs.get(
            "similar_artists",
            "similar-artists/json",
            {"artist_mbids": mbid, "algorithm": SIMILARITY_ALGORITHM},
        )
        for mbid in sorted(set(similar_for))
    }
    records = snapshot_records(popularity, similar, set(catalog))
    written = write_snapshot(records, snapshot_path)
    stats = {
        "artists": len(catalog),
        "withCounts": sum(1 for r in records if "listeners" in r.body),
        "withColistening": sum(1 for r in records if r.body.get("similar")),
        "records": written,
        "networkRequests": api.network_requests + labs.network_requests,
        "cacheHits": api.cache_hits + labs.cache_hits,
    }
    log.info("listenbrainz fetch finished", extra=stats)
    return stats
