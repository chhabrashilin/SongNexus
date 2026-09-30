"""Canonical data model.

Three layers, deliberately separated (see docs/data-model.md):

1. **Raw**        ``raw_records`` - source responses exactly as retrieved.
2. **Canonical**  entities (artists, tracks, albums, genres) with stable IDs.
3. **Facts**      credits and relationships between entities. Every fact row
                  carries provenance: source, the raw record it came from, the
                  ingestion run (and so the pipeline version) that asserted it,
                  and a confidence.

Graph edges are *not* stored: the artist graph is a read model projected from
facts at load time (docs/decisions/ADR-001-postgres-vs-graph-database.md).

The schema is portable between PostgreSQL (production) and SQLite (tests and
zero-dependency local development); JSON columns become JSONB on PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")
ID = String(36)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Sources, runs, raw data
# ---------------------------------------------------------------------------


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. "musicbrainz"
    name: Mapped[str] = mapped_column(String(128))
    homepage: Mapped[str] = mapped_column(String(256))
    license: Mapped[str] = mapped_column(String(128))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # running | succeeded | failed
    stats: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (UniqueConstraint("source_id", "request_key", name="uq_raw_source_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    kind: Mapped[str] = mapped_column(String(32))
    request_key: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    retrieved_at: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    last_seen_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class ProvenanceMixin:
    """Columns every fact carries. See docs/data-model.md#provenance."""

    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


# ---------------------------------------------------------------------------
# Canonical entities
# ---------------------------------------------------------------------------


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    sort_name: Mapped[str | None] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    artist_type: Mapped[str | None] = mapped_column(String(32))  # Person | Group | ...
    country: Mapped[str | None] = mapped_column(String(8))
    disambiguation: Mapped[str | None] = mapped_column(String(512))
    begin_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    # Hydrated artists were fetched in full (aliases, genres, relations);
    # stubs are known only from credits on other artists' releases.
    hydrated: Mapped[bool] = mapped_column(Boolean, default=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class ArtistAlias(ProvenanceMixin, Base):
    __tablename__ = "artist_aliases"
    __table_args__ = (UniqueConstraint("artist_id", "normalized_alias", name="uq_alias"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(512))
    normalized_alias: Mapped[str] = mapped_column(String(512), index=True)
    alias_type: Mapped[str] = mapped_column(String(32))  # alias | search_hint | legal_name | credited_as
    locale: Mapped[str | None] = mapped_column(String(16))


class ArtistLink(ProvenanceMixin, Base):
    """External identifiers/URLs (Discogs, Wikidata, ...): the crosswalk for
    Phase 1 cross-source entity resolution."""

    __tablename__ = "artist_links"
    __table_args__ = (UniqueConstraint("artist_id", "url", name="uq_artist_link"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    link_type: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(1024))


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), unique=True)


class ArtistGenre(ProvenanceMixin, Base):
    __tablename__ = "artist_genres"

    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), primary_key=True, index=True)
    votes: Mapped[int] = mapped_column(Integer, default=0)


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    normalized_title: Mapped[str] = mapped_column(String(512), index=True)
    primary_type: Mapped[str | None] = mapped_column(String(32))
    first_release_date: Mapped[str | None] = mapped_column(String(10))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class AlbumArtist(ProvenanceMixin, Base):
    __tablename__ = "album_artists"

    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer)
    credited_as: Mapped[str] = mapped_column(String(512))


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    normalized_title: Mapped[str] = mapped_column(String(512), index=True)
    length_ms: Mapped[int | None] = mapped_column(Integer)
    first_release_date: Mapped[str | None] = mapped_column(String(10))
    # Deduplication key: normalized base title + sorted primary artist IDs.
    dedup_key: Mapped[str] = mapped_column(String(1024), unique=True)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class AlbumTrack(ProvenanceMixin, Base):
    __tablename__ = "album_tracks"

    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True)
    disc_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), index=True)


# ---------------------------------------------------------------------------
# Facts: credits and relationships
# ---------------------------------------------------------------------------


class TrackCredit(ProvenanceMixin, Base):
    """An artist's role on a track: primary, featured, producer, vocal, ..."""

    __tablename__ = "track_credits"
    __table_args__ = (
        UniqueConstraint("track_id", "artist_id", "role", "role_detail", name="uq_track_credit"),
        Index("ix_track_credits_artist_role", "artist_id", "role"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"))
    role: Mapped[str] = mapped_column(String(32))
    role_detail: Mapped[str] = mapped_column(String(256), default="")
    credited_as: Mapped[str | None] = mapped_column(String(512))


class AlbumCredit(ProvenanceMixin, Base):
    """Release-level credits (e.g. an album producer), common on older records."""

    __tablename__ = "album_credits"
    __table_args__ = (
        UniqueConstraint("album_id", "artist_id", "role", "role_detail", name="uq_album_credit"),
        Index("ix_album_credits_artist_role", "artist_id", "role"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), index=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"))
    role: Mapped[str] = mapped_column(String(32))
    role_detail: Mapped[str] = mapped_column(String(256), default="")


class ArtistRelationship(ProvenanceMixin, Base):
    """Directed artist-to-artist facts, e.g. (member) -member_of-> (band)."""

    __tablename__ = "artist_relationships"
    __table_args__ = (UniqueConstraint("source_artist_id", "target_artist_id", "rel_type", name="uq_artist_rel"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    source_artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"), index=True)
    target_artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"), index=True)
    rel_type: Mapped[str] = mapped_column(String(32))
    attributes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    begin_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))


class EntitySourceMapping(Base):
    """How a source record was resolved to a canonical entity, and how sure we are."""

    __tablename__ = "entity_source_mappings"
    __table_args__ = (
        UniqueConstraint("source_id", "entity_type", "source_entity_id", name="uq_source_entity"),
        Index("ix_mapping_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16))  # artist | album | track
    entity_id: Mapped[str] = mapped_column(ID)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    source_entity_id: Mapped[str] = mapped_column(String(128))
    match_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(16))  # created | merged | review
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
