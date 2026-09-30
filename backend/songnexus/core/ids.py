"""Deterministic canonical identifiers.

Canonical IDs are UUIDv5 values derived from a stable key. Re-running the
pipeline on the same inputs therefore produces the same IDs, which makes
ingestion idempotent (upsert by primary key) and keeps URLs stable across
rebuilds. The key names the *first source that introduced the entity*; later
sources attach to the entity through ``entity_source_mappings`` rather than
changing its ID.
"""

from __future__ import annotations

import uuid

_NAMESPACE = uuid.UUID("5f0c2d7e-6f5b-4b7a-9c61-2b1f6a7d9e10")


def canonical_id(entity_type: str, key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{entity_type}:{key}"))


def artist_id_for_mbid(mbid: str) -> str:
    return canonical_id("artist", f"musicbrainz:{mbid}")


def album_id_for_release_group(mbid: str) -> str:
    return canonical_id("album", f"musicbrainz-release-group:{mbid}")


def track_id_for_key(dedup_key: str) -> str:
    return canonical_id("track", dedup_key)


def genre_id_for_name(normalized_name: str) -> str:
    return canonical_id("genre", normalized_name)
