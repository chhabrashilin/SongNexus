"""Bounded, cached recording browse for expanding beyond selected studio albums."""

from pathlib import Path
from uuid import UUID

from songnexus.catalog.musicbrainz.client import MusicBrainzClient
from songnexus.catalog.snapshot import RawRecord, write_snapshot

PAGE_SIZE = 100
MAX_RECORDINGS = 10_000


def fetch_recordings(
    client: MusicBrainzClient, artist: str, output: Path, *, limit: int = 500
) -> dict[str, int]:
    """Fetch bounded artist recordings, including singles and non-album releases.

    Raises:
        ValueError: Invalid MBID, limit, or an existing output path.
    """
    artist = str(UUID(artist))
    if not 1 <= limit <= MAX_RECORDINGS or output.exists():
        raise ValueError("Use a new output path and a limit from 1 to 10000")
    records: dict[str, RawRecord] = {}
    for offset in range(0, limit, PAGE_SIZE):
        page = client.get(
            "recordings",
            "recording",
            {
                "artist": artist,
                "inc": "artist-credits",
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
    return {"recordings": len(records), "networkRequests": client.network_requests}
