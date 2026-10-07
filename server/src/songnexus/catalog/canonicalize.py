"""Validate, normalize, resolve and build canonical rows from raw records.

``build_batch`` is a pure function from raw records to canonical rows. It has no
database dependency, which keeps the hardest logic (credit interpretation,
recording deduplication, relation direction) unit-testable in isolation.

Every row is keyed by a deterministic ID, and every fact row carries a
``_raw_key`` (the request key of the raw record that asserted it), which the
writer turns into a ``raw_record_id`` foreign key for provenance.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from songnexus.catalog.musicbrainz import parsers as mb
from songnexus.catalog.musicbrainz.snapshot import RawRecord
from songnexus.core import ids
from songnexus.core.model import CreditRole
from songnexus.core.text import base_title, normalize

SOURCE_ID = "musicbrainz"
# Genre associations are licensed CC BY-NC-SA, unlike the CC0 core (ADR 0003).
SUPPLEMENTARY_SOURCE_ID = "musicbrainz-supplementary"

Row = dict[str, Any]

# Confidence for recordings merged into an existing canonical recording by the
# title-plus-primary-artists rule (the representative recording gets 1.0).
RECORDING_MERGE_CONFIDENCE = 0.9

# Detail levels in increasing order; fuller data always wins over sparser data.
_DETAIL_RANK = {"stub": 0, "profile": 1, "full": 2}
_DETAIL_BY_KIND = {"artist": "full", "artist_profile": "profile"}


@dataclass
class CanonicalBatch:
    """Canonical rows built from one snapshot, keyed by primary key."""

    artists: dict[str, Row] = field(default_factory=dict)
    aliases: dict[str, Row] = field(default_factory=dict)
    links: dict[str, Row] = field(default_factory=dict)
    genres: dict[str, Row] = field(default_factory=dict)
    artist_genres: dict[tuple[str, str], Row] = field(default_factory=dict)
    labels: dict[str, Row] = field(default_factory=dict)
    releases: dict[str, Row] = field(default_factory=dict)
    release_artists: dict[tuple[str, str], Row] = field(default_factory=dict)
    release_recordings: dict[tuple[str, int, int], Row] = field(default_factory=dict)
    release_labels: dict[tuple[str, str], Row] = field(default_factory=dict)
    release_credits: dict[str, Row] = field(default_factory=dict)
    recordings: dict[str, Row] = field(default_factory=dict)
    recording_credits: dict[str, Row] = field(default_factory=dict)
    artist_relations: dict[str, Row] = field(default_factory=dict)
    mappings: dict[str, Row] = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter)
    rejected: list[dict[str, str]] = field(default_factory=list)
    ignored_relation_types: Counter[str] = field(default_factory=Counter)


_PARTIAL_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def partial_date(value: str | None) -> str | None:
    """Returns a YYYY, YYYY-MM or YYYY-MM-DD date, or None.

    MusicBrainz writes unknown parts as "?" ("????-12-23"); without a year a date
    is unusable for ordering or display, so it is dropped rather than guessed.
    """
    if not value:
        return None
    return value if _PARTIAL_DATE.match(value) else None


def _fact(raw_key: str, source_id: str = SOURCE_ID, confidence: float = 1.0) -> Row:
    return {"source_id": source_id, "_raw_key": raw_key, "confidence": confidence}


def _add_mapping(
    batch: CanonicalBatch,
    entity_type: str,
    entity_id: str,
    mbid: str,
    *,
    method: str = "musicbrainz_id",
    confidence: float = 1.0,
    decision: str = "created",
) -> None:
    mapping_id = ids.canonical_id("mapping", f"{SOURCE_ID}|{entity_type}|{mbid}")
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
    batch: CanonicalBatch,
    ref: mb.ArtistRef,
    detail_level: str = "stub",
    life_span: mb.LifeSpan | None = None,
) -> str:
    """Creates or enriches a canonical artist from a MusicBrainz reference.

    MBIDs are globally unique, so resolution is an exact source-ID match
    (confidence 1.0). Fuller data overrides sparser data, never the reverse;
    attributes only the sparser reference supplies are kept.
    """
    artist_id = ids.artist_id(ref.id)
    existing = batch.artists.get(artist_id)
    if existing is not None and _DETAIL_RANK[existing["detail_level"]] > _DETAIL_RANK[detail_level]:
        return artist_id
    row: Row = {
        "id": artist_id,
        "name": ref.name,
        "sort_name": ref.sort_name,
        "normalized_name": normalize(ref.name),
        "artist_type": ref.type,
        "country": ref.country,
        "disambiguation": ref.disambiguation or None,
        "begin_date": partial_date(life_span.begin) if life_span else None,
        "end_date": partial_date(life_span.end) if life_span else None,
        "detail_level": detail_level,
    }
    if existing is not None:
        row = {k: (v if v is not None else existing.get(k)) for k, v in row.items()}
    batch.artists[artist_id] = row
    _add_mapping(batch, "artist", artist_id, ref.id)
    return artist_id


def _add_alias(
    batch: CanonicalBatch,
    artist_id: str,
    alias: str,
    *,
    alias_type: str,
    locale: str | None,
    raw_key: str,
) -> None:
    normalized = normalize(alias)
    if not normalized or normalized == batch.artists[artist_id]["normalized_name"]:
        return
    alias_id = ids.canonical_id("alias", f"{artist_id}|{normalized}")
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
# Artist lookups
# ---------------------------------------------------------------------------


def _handle_artist(batch: CanonicalBatch, record: RawRecord) -> None:
    artist = mb.Artist.model_validate(record.body)
    artist_id = _upsert_artist(
        batch, artist, _DETAIL_BY_KIND[record.kind], life_span=artist.life_span
    )
    key = record.request_key

    for alias in artist.aliases:
        alias_type = (alias.type or "alias").lower().replace(" ", "_")
        _add_alias(
            batch, artist_id, alias.name, alias_type=alias_type, locale=alias.locale, raw_key=key
        )

    for tag in artist.genres:
        genre_norm = normalize(tag.name)
        if not genre_norm:
            continue
        genre_id = ids.genre_id(genre_norm)
        batch.genres.setdefault(
            genre_id, {"id": genre_id, "name": tag.name, "normalized_name": genre_norm}
        )
        batch.artist_genres[(artist_id, genre_id)] = {
            "artist_id": artist_id,
            "genre_id": genre_id,
            "votes": tag.count,
            **_fact(key, SUPPLEMENTARY_SOURCE_ID),
        }

    for rel in artist.relations:
        if rel.target_type == "url":
            _add_link(batch, artist_id, rel, key)
        elif rel.target_type == "artist" and rel.artist is not None:
            _add_artist_relation(batch, artist_id, rel, rel.artist, key)


def _add_link(batch: CanonicalBatch, artist_id: str, rel: mb.Relation, raw_key: str) -> None:
    if rel.url is None or rel.type not in mb.LINK_TYPES:
        return
    link_id = ids.canonical_id("link", f"{artist_id}|{rel.url.resource}")
    batch.links.setdefault(
        link_id,
        {
            "id": link_id,
            "artist_id": artist_id,
            "link_type": rel.type,
            "url": rel.url.resource,
            **_fact(raw_key),
        },
    )


def _add_artist_relation(
    batch: CanonicalBatch, artist_id: str, rel: mb.Relation, other: mb.ArtistRef, raw_key: str
) -> None:
    relation_type = mb.RELATION_TYPE_BY_NAME.get(rel.type)
    if relation_type is None:
        batch.ignored_relation_types[f"artist:{rel.type}"] += 1
        return
    other_id = _upsert_artist(batch, other)
    if other_id == artist_id:
        batch.stats["self_relations_skipped"] += 1
        return
    # "backward" means the looked-up artist is the relation's object.
    subject, obj = (other_id, artist_id) if rel.direction == "backward" else (artist_id, other_id)
    relation_id = ids.canonical_id("artist_relation", f"{subject}|{obj}|{relation_type}")
    batch.artist_relations.setdefault(
        relation_id,
        {
            "id": relation_id,
            "subject_artist_id": subject,
            "object_artist_id": obj,
            "relation_type": relation_type.value,
            "attributes": sorted(rel.attributes),
            "begin_date": partial_date(rel.begin),
            "end_date": partial_date(rel.end),
            **_fact(raw_key),
        },
    )


# ---------------------------------------------------------------------------
# Release lookups
# ---------------------------------------------------------------------------


def _handle_release(batch: CanonicalBatch, record: RawRecord) -> None:
    release = mb.Release.model_validate(record.body)
    key = record.request_key
    group = release.release_group

    release_id = ids.release_id(group.id)
    batch.releases.setdefault(
        release_id,
        {
            "id": release_id,
            "title": group.title,
            "normalized_title": normalize(group.title),
            "primary_type": group.primary_type,
            "first_release_date": partial_date(group.first_release_date or release.date),
        },
    )
    _add_mapping(batch, "release", release_id, group.id)

    for position, entry in enumerate(release.artist_credit):
        artist_id = _upsert_artist(batch, entry.artist)
        batch.release_artists.setdefault(
            (release_id, artist_id),
            {
                "release_id": release_id,
                "artist_id": artist_id,
                "position": position,
                "credited_as": entry.name,
                **_fact(key),
            },
        )

    for info in release.label_info:
        _add_release_label(batch, release_id, info, key)

    for rel in release.relations:
        _add_release_credit(batch, release_id, rel, key)

    for medium in release.media:
        for track in medium.tracks:
            recording_id = _add_recording(batch, track.recording, key)
            batch.release_recordings.setdefault(
                (release_id, medium.position, track.position),
                {
                    "release_id": release_id,
                    "disc_number": medium.position,
                    "position": track.position,
                    "recording_id": recording_id,
                    **_fact(key),
                },
            )


def _add_release_label(
    batch: CanonicalBatch, release_id: str, info: mb.LabelInfo, raw_key: str
) -> None:
    if info.label is None:
        batch.stats["label_info_without_label"] += 1
        return
    label_id = ids.label_id(info.label.id)
    batch.labels.setdefault(
        label_id,
        {
            "id": label_id,
            "name": info.label.name,
            "normalized_name": normalize(info.label.name),
            "label_type": info.label.type,
            "disambiguation": info.label.disambiguation or None,
        },
    )
    _add_mapping(batch, "label", label_id, info.label.id)
    catalog_number = (info.catalog_number or "").strip() or None
    existing = batch.release_labels.get((release_id, label_id))
    # A release can list one label several times with different catalog numbers;
    # keep the smallest so the choice is deterministic.
    if existing is not None and (
        catalog_number is None
        or (existing["catalog_number"] is not None and existing["catalog_number"] <= catalog_number)
    ):
        return
    batch.release_labels[(release_id, label_id)] = {
        "release_id": release_id,
        "label_id": label_id,
        "catalog_number": catalog_number,
        **_fact(raw_key),
    }


def _add_release_credit(
    batch: CanonicalBatch, release_id: str, rel: mb.Relation, raw_key: str
) -> None:
    if rel.target_type != "artist" or rel.artist is None:
        return
    role = mb.CREDIT_ROLE_BY_RELATION.get(rel.type)
    if role is None:
        batch.ignored_relation_types[f"release:{rel.type}"] += 1
        return
    artist_id = _upsert_artist(batch, rel.artist)
    detail = ", ".join(sorted(rel.attributes))
    credit_id = ids.canonical_id("release_credit", f"{release_id}|{artist_id}|{role}|{detail}")
    batch.release_credits.setdefault(
        credit_id,
        {
            "id": credit_id,
            "release_id": release_id,
            "artist_id": artist_id,
            "role": role.value,
            "role_detail": detail,
            **_fact(raw_key),
        },
    )


def _recording_credit(
    recording_id: str,
    artist_id: str,
    role: CreditRole,
    *,
    detail: str,
    credited_as: str | None,
    raw_key: str,
) -> Row:
    credit_id = ids.canonical_id(
        "recording_credit", f"{recording_id}|{artist_id}|{role.value}|{detail}"
    )
    return {
        "id": credit_id,
        "recording_id": recording_id,
        "artist_id": artist_id,
        "role": role.value,
        "role_detail": detail,
        "credited_as": credited_as,
        **_fact(raw_key),
    }


def _add_recording(batch: CanonicalBatch, recording: mb.Recording, raw_key: str) -> str:
    """Resolves a recording to a canonical recording, deduplicating versions.

    Two MusicBrainz recordings with the same base title ("Song (Remastered)" ->
    "Song") and the same primary artists become one canonical recording; the
    merge is recorded as a mapping with reduced confidence.
    """
    performers = [
        (_upsert_artist(batch, entry.artist), entry, role)
        for entry, role in mb.split_artist_credit(recording.artist_credit)
    ]
    primary_ids = sorted({a for a, _, role in performers if role is CreditRole.PRIMARY})
    title = base_title(recording.title)
    dedup_key = f"{normalize(title)}|{','.join(primary_ids)}"
    recording_id = ids.recording_id(dedup_key)

    if recording_id in batch.recordings:
        mapping_id = ids.canonical_id("mapping", f"{SOURCE_ID}|recording|{recording.id}")
        if mapping_id not in batch.mappings:
            batch.stats["recordings_merged"] += 1
            _add_mapping(
                batch,
                "recording",
                recording_id,
                recording.id,
                method="title_and_primary_artists",
                confidence=RECORDING_MERGE_CONFIDENCE,
                decision="merged",
            )
    else:
        batch.recordings[recording_id] = {
            "id": recording_id,
            "title": title,
            "normalized_title": normalize(title),
            "length_ms": recording.length,
            "first_release_date": partial_date(recording.first_release_date),
            "dedup_key": dedup_key,
        }
        _add_mapping(batch, "recording", recording_id, recording.id)

    for artist_id, entry, role in performers:
        row = _recording_credit(
            recording_id, artist_id, role, detail="", credited_as=entry.name, raw_key=raw_key
        )
        batch.recording_credits.setdefault(row["id"], row)
        _add_alias(
            batch, artist_id, entry.name, alias_type="credited_as", locale=None, raw_key=raw_key
        )

    for rel in recording.relations:
        if rel.target_type != "artist" or rel.artist is None:
            continue
        credit_role = mb.CREDIT_ROLE_BY_RELATION.get(rel.type)
        if credit_role is None:
            batch.ignored_relation_types[f"recording:{rel.type}"] += 1
            continue
        artist_id = _upsert_artist(batch, rel.artist)
        row = _recording_credit(
            recording_id,
            artist_id,
            credit_role,
            detail=", ".join(sorted(rel.attributes)),
            credited_as=None,
            raw_key=raw_key,
        )
        batch.recording_credits.setdefault(row["id"], row)
    return recording_id


_HANDLERS: dict[str, Callable[[CanonicalBatch, RawRecord], None]] = {
    "artist": _handle_artist,
    "artist_profile": _handle_artist,
    "release": _handle_release,
}
# Fuller artist lookups first, so stub references never shadow them.
_KIND_ORDER = {"artist": 0, "artist_profile": 1}


def build_batch(records: Iterable[RawRecord]) -> CanonicalBatch:
    """Builds canonical rows from raw records, deterministically.

    Records that fail validation are rejected and listed in
    ``CanonicalBatch.rejected``; they never abort the batch. Search and browse
    records are used only for selection at fetch time and are skipped here.
    """
    batch = CanonicalBatch()
    ordered = sorted(records, key=lambda r: (_KIND_ORDER.get(r.kind, 2), r.request_key))
    for record in ordered:
        batch.stats[f"records:{record.kind}"] += 1
        handler = _HANDLERS.get(record.kind)
        if handler is None:
            continue
        try:
            handler(batch, record)
        except ValidationError as exc:
            batch.rejected.append({"requestKey": record.request_key, "error": str(exc)[:500]})
            batch.stats["records_rejected"] += 1
    return batch
