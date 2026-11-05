"""AcousticBrainz adapter (https://acousticbrainz.org, CC0): audio descriptors by recording MBID.

AcousticBrainz stopped collecting data in 2022; its API still serves the final
dataset. Both bulk endpoints take up to 25 recording MBIDs per request. Raw
responses are cached locally (git-ignored, about 1 MB per 25 recordings); the
committed snapshot keeps, per recording, only the fields SongNexus uses, copied
verbatim from the first submission (offset 0).

Not used: the voice-gender classifier (it labels people, and song comparison
does not need it) and the genre classifiers (genres come from Discogs and
MusicBrainz, ADR 0005).
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

BATCH = 25  # the API's maximum per bulk request
ENDPOINTS = ("low-level", "high-level")

# Fields kept from each response, as (path in the submission, name in the snapshot).
LOW_LEVEL_FIELDS = (
    (("rhythm", "bpm"), "bpm"),
    (("rhythm", "danceability"), "danceability_raw"),
    (("tonal", "key_key"), "key"),
    (("tonal", "key_scale"), "scale"),
    (("tonal", "key_strength"), "key_strength"),
    (("lowlevel", "average_loudness"), "average_loudness"),
    (("lowlevel", "dynamic_complexity"), "dynamic_complexity"),
    (("metadata", "audio_properties", "length"), "length_s"),
)
HIGH_LEVEL_CLASSIFIERS = (
    ("danceability", "danceable"),
    ("mood_acoustic", "acoustic"),
    ("mood_aggressive", "aggressive"),
    ("mood_electronic", "electronic"),
    ("mood_happy", "happy"),
    ("mood_party", "party"),
    ("mood_relaxed", "relaxed"),
    ("mood_sad", "sad"),
    ("voice_instrumental", "instrumental"),
    ("tonal_atonal", "tonal"),
    ("timbre", "bright"),
)


class AcousticBrainzError(SourceRequestError):
    """An AcousticBrainz request failed permanently."""


class AcousticBrainzClient(PoliteClient):
    """Fetches AcousticBrainz bulk responses as ``RawRecord`` values."""

    error_type = AcousticBrainzError

    def __init__(
        self,
        *,
        base_url: str,
        cache_dir: Path,
        contact: str = "",
        min_interval_s: float = 1.0,
        http: httpx.Client | None = None,
    ) -> None:
        """Creates a client for the API at ``base_url`` (``.../api/v1``)."""
        super().__init__(
            source="acousticbrainz",
            base_url=base_url,
            cache_dir=cache_dir,
            contact=contact,
            min_interval_s=min_interval_s,
            # The service is slow (tens of seconds per bulk response) and sometimes
            # times out; be patient rather than fail a resumable fetch.
            max_retries=8,
            timeout_s=180.0,
            remember=False,  # ~1 MB per response: digest each batch, keep nothing
            http=http,
        )


def _dig(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def extract(low: dict[str, Any] | None, high: dict[str, Any] | None) -> dict[str, Any]:
    """Returns the kept fields of one recording's first submission.

    High-level classifiers are kept as the probability of the named class (for
    example ``instrumental`` is P(instrumental) from ``voice_instrumental``).
    """
    out: dict[str, Any] = {}
    if low:
        for path, name in LOW_LEVEL_FIELDS:
            value = _dig(low, path)
            if value is not None:
                out[name] = value
    if high:
        for classifier, value_name in HIGH_LEVEL_CLASSIFIERS:
            probability = _dig(high, ("highlevel", classifier, "all", value_name))
            if isinstance(probability, int | float):
                out[value_name] = probability
    return out


def snapshot_records(responses: Iterable[RawRecord]) -> list[RawRecord]:
    """Returns one record per recording found, from bulk low- and high-level responses."""
    low: dict[str, tuple[RawRecord, dict[str, Any]]] = {}
    high: dict[str, dict[str, Any]] = {}
    for response in responses:
        for mbid, submissions in response.body.items():
            if mbid == "mbid_mapping" or not isinstance(submissions, dict):
                continue
            first = submissions.get("0")
            if not isinstance(first, dict):
                continue
            if response.kind == "low-level":
                low[mbid] = (response, first)
            else:
                high[mbid] = first
    records = []
    for mbid in sorted(set(low) | set(high)):
        source, low_body = low.get(mbid, (None, None))
        fields = extract(low_body, high.get(mbid))
        if not fields:
            continue
        records.append(
            RawRecord(
                kind="descriptors",
                request_key=f"recording/{mbid}",
                url=f"https://acousticbrainz.org/{mbid}",
                retrieved_at=source.retrieved_at if source else "",
                body={"recording": mbid, "submission": 0, **fields},
            )
        )
    return records


def run_fetch(
    client: AcousticBrainzClient,
    *,
    recording_ids: Iterable[str],
    snapshot_path: Path,
    cached_only: bool = False,
) -> dict[str, Any]:
    """Fetches descriptors for the recordings and writes the snapshot.

    With ``cached_only``, nothing is requested: the snapshot is built from the
    batches already in the local cache (for example while a slow fetch is still
    running), and the stats say how many batches were missing.

    Raises:
        AcousticBrainzError: A request failed permanently.
    """
    mbids = sorted(set(recording_ids))
    records: list[RawRecord] = []
    missing_batches = 0
    for start in range(0, len(mbids), BATCH):
        batch = ";".join(mbids[start : start + BATCH])
        params: dict[str, str | int] = {"recording_ids": batch}
        if cached_only:
            cached = [client.cached_get(e, params) for e in ENDPOINTS]
            if any(c is None for c in cached):
                missing_batches += 1
                continue
            responses = [c for c in cached if c is not None]
        else:
            responses = [client.get(e, e, params) for e in ENDPOINTS]
        # Extract each batch as it arrives; the full responses are dropped.
        records.extend(snapshot_records(responses))
    records.sort(key=lambda r: r.request_key)
    written = write_snapshot(records, snapshot_path)
    stats = {
        "recordings": len(mbids),
        "withDescriptors": len(records),
        "coverage": round(len(records) / len(mbids), 4) if mbids else None,
        "missingBatches": missing_batches,
        "records": written,
        "networkRequests": client.network_requests,
        "cacheHits": client.cache_hits,
    }
    log.info("acousticbrainz fetch finished", extra=stats)
    return stats
