"""Bounded, cached recording browse for expanding beyond selected studio albums."""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from songnexus.catalog.musicbrainz.client import MusicBrainzClient
from songnexus.catalog.snapshot import RawRecord, write_snapshot

PAGE_SIZE = 100
MAX_RECORDINGS = 10_000
# Performers come from the artist credit; producers, engineers, mixers and
# instrumentalists only appear as artist relationships on the recording.
RECORDING_INC = "artist-credits+artist-rels"


def fetch_recordings(
    client: MusicBrainzClient,
    artist: str | Sequence[str],
    output: Path,
    *,
    limit: int = 500,
) -> dict[str, int]:
    """Fetch bounded recordings (with credits) for one or more artists.

    ``limit`` applies per artist. The client's on-disk cache makes a re-run after
    an interruption cheap, so a failed fetch loses no completed pages.

    Raises:
        ValueError: Invalid MBID, limit, or an existing output path.
    """
    artists = [artist] if isinstance(artist, str) else list(artist)
    artists = [str(UUID(a)) for a in dict.fromkeys(artists)]
    if not artists or not 1 <= limit <= MAX_RECORDINGS or output.exists():
        raise ValueError("Use a new output path and a limit from 1 to 10000")
    records: dict[str, RawRecord] = {}
    for artist_id in artists:
        for offset in range(0, limit, PAGE_SIZE):
            page = client.get(
                "recordings",
                "recording",
                {
                    "artist": artist_id,
                    "inc": RECORDING_INC,
                    "limit": min(PAGE_SIZE, limit - offset),
                    "offset": offset,
                },
            )
            entries = page.body.get("recordings", [])
            for entry in entries:
                key = f"recording/{entry['id']}"
                records[key] = RawRecord("recording", key, page.url, page.retrieved_at, entry)
            if not entries or offset + len(entries) >= page.body.get("recording-count", 0):
                break
    write_snapshot(records.values(), output)
    return {
        "artists": len(artists),
        "recordings": len(records),
        "networkRequests": client.network_requests,
    }
