"""Deterministic canonical identifiers.

Canonical IDs are UUIDv5 values derived from a stable key, so re-running the
pipeline on the same input yields the same IDs. Ingestion is therefore an
idempotent upsert and URLs stay stable across rebuilds. The key names the source
record that *introduced* an entity; later sources attach through source mappings
and never re-key it.
"""

from __future__ import annotations

import uuid

_NAMESPACE = uuid.UUID("5f0c2d7e-6f5b-4b7a-9c61-2b1f6a7d9e10")


def canonical_id(entity_type: str, key: str) -> str:
    """Returns the canonical ID for an entity type and its stable key."""
    return str(uuid.uuid5(_NAMESPACE, f"{entity_type}:{key}"))


def artist_id(musicbrainz_id: str) -> str:
    """Returns the canonical artist ID for a MusicBrainz artist ID."""
    return canonical_id("artist", f"musicbrainz:{musicbrainz_id}")


def release_id(musicbrainz_release_group_id: str) -> str:
    """Returns the canonical release ID for a MusicBrainz release group ID."""
    return canonical_id("release", f"musicbrainz-release-group:{musicbrainz_release_group_id}")


def recording_id(dedup_key: str) -> str:
    """Returns the canonical recording ID for a deduplication key."""
    return canonical_id("recording", dedup_key)


def label_id(musicbrainz_id: str) -> str:
    """Returns the canonical label ID for a MusicBrainz label ID."""
    return canonical_id("label", f"musicbrainz:{musicbrainz_id}")


def genre_id(normalized_name: str) -> str:
    """Returns the canonical genre ID for a normalized genre name."""
    return canonical_id("genre", normalized_name)
