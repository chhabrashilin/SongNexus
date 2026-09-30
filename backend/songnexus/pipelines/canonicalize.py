"""Stages 1-4: validate -> normalize -> resolve -> build canonical rows.

``build_batch`` is a pure function from raw records to canonical rows. It has
no database dependency, which keeps the hardest logic (credit interpretation,
track deduplication, relationship direction) unit-testable in isolation.

Every row is keyed by a deterministic ID, and every fact row carries a
``_raw_key`` (the request key of the raw record that asserted it), which the
writer turns into a ``raw_record_id`` foreign key for provenance.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from songnexus.core.ids import (
    album_id_for_release_group,
    artist_id_for_mbid,
    canonical_id,
    genre_id_for_name,
    track_id_for_key,
)
from songnexus.core.text import base_title, normalize
from songnexus.integrations.musicbrainz import parsers as mb
from songnexus.integrations.musicbrainz.snapshot import RawRecord

SOURCE_ID = "musicbrainz"
Row = dict[str, Any]

# Confidence for recordings merged into an existing canonical track by the
# title+primary-artist dedup rule (vs. 1.0 for the representative recording).
TRACK_MERGE_CONFIDENCE = 0.9


@dataclass
class CanonicalBatch:
    artists: dict[str, Row] = field(default_factory=dict)
    aliases: dict[str, Row] = field(default_factory=dict)
    links: dict[str, Row] = field(default_factory=dict)
    genres: dict[str, Row] = field(default_factory=dict)
    artist_genres: dict[tuple[str, str], Row] = field(default_factory=dict)
    albums: dict[str, Row] = field(default_factory=dict)
    album_artists: dict[tuple[str, str], Row] = field(default_factory=dict)
    album_tracks: dict[tuple[str, int, int], Row] = field(default_factory=dict)
    album_credits: dict[str, Row] = field(default_factory=dict)
    tracks: dict[str, Row] = field(default_factory=dict)
    track_credits: dict[str, Row] = field(default_factory=dict)
    artist_relationships: dict[str, Row] = field(default_factory=dict)
    mappings: dict[str, Row] = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter)
    rejected: list[dict[str, str]] = field(default_factory=list)
    ignored_relation_types: Counter[str] = field(default_factory=Counter)


def _fact(raw_key: str, confidence: float = 1.0) -> Row:
    return {"source_id": SOURCE_ID, "_raw_key": raw_key, "confidence": confidence}


def _add_mapping(
    batch: CanonicalBatch, entity_type: str, entity_id: str, mbid: str, method: str, confidence: float, decision: str
) -> None:
    mapping_id = canonical_id("mapping", f"{SOURCE_ID}|{entity_type}|{mbid}")
    batch.mappings.setdefault(
        mapping_id,
        {
            "id": mapping_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source_id": SOURCE_ID,
            "source_entity_id": mbid,
            "match_method": method,
            "confidence": confidence,
            "decision": decision,
        },
    )


def _upsert_artist(
    batch: CanonicalBatch, ref: mb.ArtistRef, hydrated: bool, life_span: mb.LifeSpan | None = None
) -> str:
    """Create or enrich a canonical artist from a MusicBrainz reference.

    MBIDs are globally unique, so resolution here is an exact source-ID match
    (confidence 1.0). Fuller data (from a lookup) overrides stub data (from a
    credit), never the reverse.
    """
    artist_id = artist_id_for_mbid(ref.id)
    existing = batch.artists.get(artist_id)
    if existing is not None and existing["hydrated"] and not hydrated:
        return artist_id
    row = {
        "id": artist_id,
        "name": ref.name,
        "sort_name": ref.sort_name,
        "normalized_name": normalize(ref.name),
        "artist_type": ref.type,
        "country": ref.country,
        "disambiguation": ref.disambiguation or None,
        "begin_date": life_span.begin if life_span else None,
        "end_date": life_span.end if life_span else None,
        "hydrated": hydrated,
    }
    if existing is not None:
        # Keep attributes a previous reference supplied but this one lacks.
        row = {k: (v if v is not None else existing.get(k)) for k, v in row.items()}
    batch.artists[artist_id] = row
    _add_mapping(batch, "artist", artist_id, ref.id, "musicbrainz_id", 1.0, "created")
    return artist_id


def _add_alias(
    batch: CanonicalBatch, artist_id: str, alias: str, alias_type: str, locale: str | None, raw_key: str
) -> None:
    normalized = normalize(alias)
    artist = batch.artists[artist_id]
    if not normalized or normalized == artist["normalized_name"]:
        return
    alias_id = canonical_id("alias", f"{artist_id}|{normalized}")
    batch.aliases.setdefault(
        alias_id,
        {
            "id": alias_id,
            "artist_id": artist_id,
            "alias": alias,
            "normalized_alias": normalized,
            "alias_type": alias_type,
            "locale": locale,
            **_fact(raw_key),
        },
    )


# ---------------------------------------------------------------------------
# Record handlers
# ---------------------------------------------------------------------------


def _handle_artist(batch: CanonicalBatch, record: RawRecord) -> None:
    artist = mb.Artist.model_validate(record.body)
    artist_id = _upsert_artist(batch, artist, hydrated=True, life_span=artist.life_span)
    key = record.request_key

    for alias in artist.aliases:
        alias_type = (alias.type or "alias").lower().replace(" ", "_")
        _add_alias(batch, artist_id, alias.name, alias_type, alias.locale, key)

    for tag in artist.genres:
        genre_norm = normalize(tag.name)
        genre_id = genre_id_for_name(genre_norm)
        batch.genres.setdefault(genre_id, {"id": genre_id, "name": tag.name, "normalized_name": genre_norm})
        batch.artist_genres[(artist_id, genre_id)] = {
            "artist_id": artist_id,
            "genre_id": genre_id,
            "votes": tag.count,
            **_fact(key),
        }

    for rel in artist.relations:
        if rel.target_type == "url" and rel.url is not None:
            if rel.type in mb.LINK_TYPES:
                link_id = canonical_id("link", f"{artist_id}|{rel.url.resource}")
                batch.links.setdefault(
                    link_id,
                    {
                        "id": link_id,
                        "artist_id": artist_id,
                        "link_type": rel.type,
                        "url": rel.url.resource,
                        **_fact(key),
                    },
                )
            continue
        if rel.target_type != "artist" or rel.artist is None:
            continue
        rel_type = mb.ARTIST_REL_TYPE.get(rel.type)
        if rel_type is None:
            batch.ignored_relation_types[f"artist:{rel.type}"] += 1
            continue
        other_id = _upsert_artist(batch, rel.artist, hydrated=False)
        # "forward" means the looked-up artist is the subject of the relation.
        source, target = (artist_id, other_id) if rel.direction != "backward" else (other_id, artist_id)
        rel_id = canonical_id("artist_rel", f"{source}|{target}|{rel_type}")
        batch.artist_relationships.setdefault(
            rel_id,
            {
                "id": rel_id,
                "source_artist_id": source,
                "target_artist_id": target,
                "rel_type": rel_type,
                "attributes": sorted(rel.attributes),
                "begin_date": rel.begin,
                "end_date": rel.end,
                **_fact(key),
            },
        )


def _credit_row(track_id: str, artist_id: str, role: str, detail: str, credited_as: str | None, raw_key: str) -> Row:
    credit_id = canonical_id("track_credit", f"{track_id}|{artist_id}|{role}|{detail}")
    return {
        "id": credit_id,
        "track_id": track_id,
        "artist_id": artist_id,
        "role": role,
        "role_detail": detail,
        "credited_as": credited_as,
        **_fact(raw_key),
    }


def _handle_release(batch: CanonicalBatch, record: RawRecord) -> None:
    release = mb.Release.model_validate(record.body)
    key = record.request_key
    rg = release.release_group

    album_id = album_id_for_release_group(rg.id)
    batch.albums.setdefault(
        album_id,
        {
            "id": album_id,
            "title": rg.title,
            "normalized_title": normalize(rg.title),
            "primary_type": rg.primary_type,
            "first_release_date": rg.first_release_date or release.date,
        },
    )
    _add_mapping(batch, "album", album_id, rg.id, "musicbrainz_id", 1.0, "created")

    for position, entry in enumerate(release.artist_credit):
        artist_id = _upsert_artist(batch, entry.artist, hydrated=False)
        batch.album_artists.setdefault(
            (album_id, artist_id),
            {
                "album_id": album_id,
                "artist_id": artist_id,
                "position": position,
                "credited_as": entry.name,
                **_fact(key),
            },
        )

    for rel in release.relations:
        _add_album_credit(batch, album_id, rel, key)

    for medium in release.media:
        for track in medium.tracks:
            track_id = _add_recording(batch, track.recording, key)
            batch.album_tracks.setdefault(
                (album_id, medium.position, track.position),
                {
                    "album_id": album_id,
                    "disc_number": medium.position,
                    "position": track.position,
                    "track_id": track_id,
                    **_fact(key),
                },
            )


def _add_album_credit(batch: CanonicalBatch, album_id: str, rel: mb.Relation, raw_key: str) -> None:
    if rel.target_type != "artist" or rel.artist is None:
        return
    role = mb.CREDIT_ROLE_BY_RELATION.get(rel.type)
    if role is None:
        batch.ignored_relation_types[f"release:{rel.type}"] += 1
        return
    artist_id = _upsert_artist(batch, rel.artist, hydrated=False)
    detail = ", ".join(sorted(rel.attributes))
    credit_id = canonical_id("album_credit", f"{album_id}|{artist_id}|{role}|{detail}")
    batch.album_credits.setdefault(
        credit_id,
        {
            "id": credit_id,
            "album_id": album_id,
            "artist_id": artist_id,
            "role": role,
            "role_detail": detail,
            **_fact(raw_key),
        },
    )


def _add_recording(batch: CanonicalBatch, recording: mb.Recording, raw_key: str) -> str:
    """Resolve a recording to a canonical track (deduplicating versions)."""
    performers = [
        (_upsert_artist(batch, entry.artist, hydrated=False), entry, role)
        for entry, role in mb.split_artist_credit(recording.artist_credit)
    ]
    primary_ids = sorted({artist_id for artist_id, _, role in performers if role == "primary"})
    title = base_title(recording.title)
    dedup_key = f"{normalize(title)}|{','.join(primary_ids)}"
    track_id = track_id_for_key(dedup_key)

    if track_id in batch.tracks:
        existing_mapping = batch.mappings.get(canonical_id("mapping", f"{SOURCE_ID}|track|{recording.id}"))
        if existing_mapping is None:
            batch.stats["recordings_merged"] += 1
            _add_mapping(
                batch, "track", track_id, recording.id, "title_and_primary_artists", TRACK_MERGE_CONFIDENCE, "merged"
            )
    else:
        batch.tracks[track_id] = {
            "id": track_id,
            "title": title,
            "normalized_title": normalize(title),
            "length_ms": recording.length,
            "first_release_date": recording.first_release_date,
            "dedup_key": dedup_key,
        }
        _add_mapping(batch, "track", track_id, recording.id, "musicbrainz_id", 1.0, "created")

    for artist_id, entry, role in performers:
        row = _credit_row(track_id, artist_id, role, "", entry.name, raw_key)
        batch.track_credits.setdefault(row["id"], row)
        if normalize(entry.name) != batch.artists[artist_id]["normalized_name"]:
            _add_alias(batch, artist_id, entry.name, "credited_as", None, raw_key)

    for rel in recording.relations:
        if rel.target_type != "artist" or rel.artist is None:
            continue
        credit_role = mb.CREDIT_ROLE_BY_RELATION.get(rel.type)
        if credit_role is None:
            batch.ignored_relation_types[f"recording:{rel.type}"] += 1
            continue
        artist_id = _upsert_artist(batch, rel.artist, hydrated=False)
        row = _credit_row(track_id, artist_id, credit_role, ", ".join(sorted(rel.attributes)), None, raw_key)
        batch.track_credits.setdefault(row["id"], row)
    return track_id


_HANDLERS = {"artist": _handle_artist, "release": _handle_release}


def build_batch(records: Iterable[RawRecord]) -> CanonicalBatch:
    batch = CanonicalBatch()
    # Hydrated artist lookups first, so stub references never shadow them.
    ordered = sorted(records, key=lambda r: (r.kind != "artist", r.request_key))
    for record in ordered:
        batch.stats[f"records:{record.kind}"] += 1
        handler = _HANDLERS.get(record.kind)
        if handler is None:
            continue  # search/browse records are used only for selection at fetch time
        try:
            handler(batch, record)
        except ValidationError as exc:
            batch.rejected.append({"request_key": record.request_key, "error": str(exc)[:500]})
            batch.stats["records_rejected"] += 1
    return batch
