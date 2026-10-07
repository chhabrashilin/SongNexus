"""Relational schema of the catalog.

Three layers, deliberately separated:

1. Raw: ``raw_records`` holds source responses exactly as retrieved.
2. Canonical entities: artists, releases, recordings, labels and genres, keyed by
   deterministic IDs (``songnexus.core.ids``).
3. Facts: credits, relations, aliases, links, genre and label associations.
   Every fact row carries provenance: its source, the raw record that asserted
   it, the ingestion run (and so pipeline version) that wrote it, and a
   confidence.

Graph edges are not stored. The artist graph is a read model projected from
facts at load time.

The schema is portable between PostgreSQL (production) and SQLite (tests and
zero-dependency development). JSON columns become JSONB on PostgreSQL. Changes
go through Alembic migrations (``server/migrations``), never ``create_all`` in
production.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")
ID = String(36)
NAME = String(512)
DATE = String(10)

# Deterministic constraint names, so migrations are reviewable and portable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    # First column only: PostgreSQL truncates identifiers beyond 63 bytes.
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with the project naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------------------
# Sources, runs, raw data
# ---------------------------------------------------------------------------


class DataSource(Base):
    """A provider of facts, with the license its data is used under."""

    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    homepage: Mapped[str] = mapped_column(String(256))
    license: Mapped[str] = mapped_column(String(128))


class IngestionRun(Base):
    """One execution of the ingestion pipeline over one snapshot."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adapter: Mapped[str] = mapped_column(String(64))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # running | succeeded | failed
    stats: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class RawRecord(Base):
    """A source response, kept verbatim as the provenance anchor for facts."""

    __tablename__ = "raw_records"
    __table_args__ = (UniqueConstraint("source_id", "request_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    kind: Mapped[str] = mapped_column(String(32))
    request_key: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(String(2048))
    retrieved_at: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    last_seen_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class ProvenanceMixin:
    """Columns every fact carries."""

    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_records.id"))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


# ---------------------------------------------------------------------------
# Canonical entities
# ---------------------------------------------------------------------------


class Artist(Base):
    """A person, group, orchestra or other performing entity."""

    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(NAME)
    sort_name: Mapped[str | None] = mapped_column(NAME)
    normalized_name: Mapped[str] = mapped_column(NAME, index=True)
    artist_type: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(8))
    disambiguation: Mapped[str | None] = mapped_column(NAME)
    begin_date: Mapped[str | None] = mapped_column(DATE)
    end_date: Mapped[str | None] = mapped_column(DATE)
    # "full": looked up with relationships (seeds); "profile": aliases and
    # genres; "stub": known only from a credit or relation on another entity.
    detail_level: Mapped[str] = mapped_column(String(8))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class Release(Base):
    """An album-level release (a MusicBrainz release group)."""

    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    title: Mapped[str] = mapped_column(NAME)
    normalized_title: Mapped[str] = mapped_column(NAME, index=True)
    primary_type: Mapped[str | None] = mapped_column(String(32))
    first_release_date: Mapped[str | None] = mapped_column(DATE)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class Recording(Base):
    """A song as performed: versions of one performance are deduplicated into one."""

    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    title: Mapped[str] = mapped_column(NAME)
    normalized_title: Mapped[str] = mapped_column(NAME, index=True)
    length_ms: Mapped[int | None] = mapped_column(Integer)
    first_release_date: Mapped[str | None] = mapped_column(DATE)
    # Normalized base title plus sorted primary artist IDs.
    dedup_key: Mapped[str] = mapped_column(String(2048), unique=True)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class Label(Base):
    """A record label."""

    __tablename__ = "labels"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(NAME)
    normalized_name: Mapped[str] = mapped_column(NAME, index=True)
    label_type: Mapped[str | None] = mapped_column(String(64))
    disambiguation: Mapped[str | None] = mapped_column(NAME)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


class Genre(Base):
    """A genre, identified by its normalized name."""

    __tablename__ = "genres"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), unique=True)


class EntitySourceMapping(Base):
    """How a source record was resolved to a canonical entity, and how sure we are."""

    __tablename__ = "entity_source_mappings"
    __table_args__ = (
        UniqueConstraint("source_id", "entity_type", "source_entity_id"),
        Index("ix_entity_source_mappings_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16))  # artist|release|recording|label
    entity_id: Mapped[str] = mapped_column(ID)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_entity_id: Mapped[str] = mapped_column(String(128))
    match_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(16))  # created | merged
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class ArtistAlias(ProvenanceMixin, Base):
    """Another name for an artist: other scripts, legal name, credited-as name."""

    __tablename__ = "artist_aliases"
    __table_args__ = (UniqueConstraint("artist_id", "normalized_alias"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(NAME)
    normalized_alias: Mapped[str] = mapped_column(NAME, index=True)
    alias_type: Mapped[str] = mapped_column(String(32))
    locale: Mapped[str | None] = mapped_column(String(16))


class ArtistLink(ProvenanceMixin, Base):
    """An external URL for an artist (official site, Wikidata, streaming)."""

    __tablename__ = "artist_links"
    __table_args__ = (UniqueConstraint("artist_id", "url"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    link_type: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(2048))


class ArtistGenre(ProvenanceMixin, Base):
    """A genre association with its vote count (licensed separately, ADR 0003)."""

    __tablename__ = "artist_genres"

    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), primary_key=True, index=True)
    votes: Mapped[int] = mapped_column(Integer, default=0)


class ReleaseArtist(ProvenanceMixin, Base):
    """An artist in a release's artist credit."""

    __tablename__ = "release_artists"

    release_id: Mapped[str] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer)
    credited_as: Mapped[str] = mapped_column(NAME)


class ReleaseRecording(ProvenanceMixin, Base):
    """A recording's slot on a release's tracklist."""

    __tablename__ = "release_recordings"

    release_id: Mapped[str] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    disc_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), index=True)


class ReleaseLabel(ProvenanceMixin, Base):
    """A label credit on a release, with its catalog number."""

    __tablename__ = "release_labels"

    release_id: Mapped[str] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[str] = mapped_column(ForeignKey("labels.id"), primary_key=True, index=True)
    catalog_number: Mapped[str | None] = mapped_column(String(128))


class ReleaseCredit(ProvenanceMixin, Base):
    """A release-level credit (an album producer), common on older records."""

    __tablename__ = "release_credits"
    __table_args__ = (
        UniqueConstraint("release_id", "artist_id", "role", "role_detail"),
        Index("ix_release_credits_artist_role", "artist_id", "role"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), index=True
    )
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"))
    role: Mapped[str] = mapped_column(String(32))
    role_detail: Mapped[str] = mapped_column(String(256), default="")


class RecordingCredit(ProvenanceMixin, Base):
    """An artist's role on a recording: primary, featured, producer, vocal, ..."""

    __tablename__ = "recording_credits"
    __table_args__ = (
        UniqueConstraint("recording_id", "artist_id", "role", "role_detail"),
        Index("ix_recording_credits_artist_role", "artist_id", "role"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    recording_id: Mapped[str] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), index=True
    )
    artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"))
    role: Mapped[str] = mapped_column(String(32))
    role_detail: Mapped[str] = mapped_column(String(256), default="")
    credited_as: Mapped[str | None] = mapped_column(NAME)


class ArtistRelation(ProvenanceMixin, Base):
    """A directed artist-to-artist fact: ``subject -relation_type-> object``."""

    __tablename__ = "artist_relations"
    __table_args__ = (UniqueConstraint("subject_artist_id", "object_artist_id", "relation_type"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    subject_artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"), index=True)
    object_artist_id: Mapped[str] = mapped_column(ForeignKey("artists.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(32))
    attributes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    begin_date: Mapped[str | None] = mapped_column(DATE)
    end_date: Mapped[str | None] = mapped_column(DATE)


ENTITY_MODELS: dict[str, type[Base]] = {
    "artist": Artist,
    "release": Release,
    "recording": Recording,
    "label": Label,
}


# ---------------------------------------------------------------------------
# User data (plan §15.2). Personal data lives only here, never in logs.
# ---------------------------------------------------------------------------


class User(Base):
    """An account. Email and name stay in Firebase; we store only the Firebase UID.

    On deletion the UID is cleared at once (so signing in again creates a new,
    empty account) and the row is purged within 30 days.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    age_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class UserSession(Base):
    """A signed-in browser. Only the SHA-256 of the session token is stored (ADR 0002)."""

    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Preferences(Base):
    """A user's settings, versioned by an ETag (AIP-154)."""

    __tablename__ = "preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    genre_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    categories: Mapped[list[str]] = mapped_column(JsonType, default=list)
    theme: Mapped[str] = mapped_column(String(16))
    etag: Mapped[str] = mapped_column(String(32))
    update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BlockedArtist(Base):
    """An artist a user never wants to see in lists or paths (US-17)."""

    __tablename__ = "blocked_artists"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Not a foreign key: blocks survive catalog rebuilds that drop an artist.
    artist_id: Mapped[str] = mapped_column(ID, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Profile(Base):
    """A user's profile: Top 5 artists, private by default (US-09)."""

    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    top_artist_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    visibility: Mapped[str] = mapped_column(String(16))
    etag: Mapped[str] = mapped_column(String(32))
    update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    """An account-changing action, for disputes (plan §19, repudiation).

    Holds no IP addresses or request bodies; removed with the account.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
