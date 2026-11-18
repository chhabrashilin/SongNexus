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
    Boolean,
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
from sqlalchemy.sql import true

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
    entity_type: Mapped[str] = mapped_column(String(16))  # artist|release|recording|label|genre
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
    """A genre association with its vote count, per source (ADR 0003, ADR 0005).

    Sources count votes in their own unit (MusicBrainz tag votes, Discogs masters
    tagged), so the source is part of the key and shares are computed per source.
    """

    __tablename__ = "artist_genres"

    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id"), primary_key=True, index=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), primary_key=True, index=True
    )
    votes: Mapped[int] = mapped_column(Integer, default=0)


class RecordingDescriptors(ProvenanceMixin, Base):
    """Audio descriptors of a recording (AcousticBrainz, CC0), for song comparison.

    ``moods`` maps classifier names (``happy``, ``instrumental``, ...) to the
    probability of that class; see ``catalog.acousticbrainz``.
    """

    __tablename__ = "recording_descriptors"

    recording_id: Mapped[str] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), primary_key=True, index=True
    )
    source_recording_id: Mapped[str] = mapped_column(String(64))
    bpm: Mapped[float | None] = mapped_column(Float)
    key: Mapped[str | None] = mapped_column(String(4))
    scale: Mapped[str | None] = mapped_column(String(8))
    key_strength: Mapped[float | None] = mapped_column(Float)
    length_s: Mapped[float | None] = mapped_column(Float)
    average_loudness: Mapped[float | None] = mapped_column(Float)
    dynamic_complexity: Mapped[float | None] = mapped_column(Float)
    moods: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class ArtistAudience(ProvenanceMixin, Base):
    """An artist's aggregate audience on a listening service (ListenBrainz)."""

    __tablename__ = "artist_audiences"

    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), primary_key=True, index=True
    )
    listeners: Mapped[int] = mapped_column(Integer)
    listens: Mapped[int] = mapped_column(Integer)


class ArtistCoListening(ProvenanceMixin, Base):
    """``other_artist_id`` is often played with ``artist_id`` (rank 1 = most), per a service."""

    __tablename__ = "artist_colistening"

    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    other_artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), primary_key=True, index=True
    )
    score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)


class ArtistImage(Base):
    """A freely licensed photo of an artist from Wikimedia Commons (ADR 0009).

    Found through the artist's Wikidata item (P434 MusicBrainz ID, P18 image).
    One row per artist; ``songnexus fetch-images`` replaces it on each run.
    Attribution (author, license, file page) is stored with the URLs because
    the license requires it to travel with the image wherever it is shown.
    """

    __tablename__ = "artist_images"

    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    wikidata_id: Mapped[str] = mapped_column(String(32))
    commons_file: Mapped[str] = mapped_column(String(512))
    thumbnail_url: Mapped[str] = mapped_column(String(2048))
    large_url: Mapped[str] = mapped_column(String(2048))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    page_url: Mapped[str] = mapped_column(String(2048))
    author: Mapped[str | None] = mapped_column(String(512))
    license: Mapped[str] = mapped_column(String(128))
    license_url: Mapped[str | None] = mapped_column(String(2048))
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenreParent(ProvenanceMixin, Base):
    """``genre_id`` is a kind of ``parent_genre_id`` (e.g. trap is a kind of hip hop)."""

    __tablename__ = "genre_parents"

    genre_id: Mapped[str] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True
    )
    parent_genre_id: Mapped[str] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), primary_key=True, index=True
    )


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
    # Development demo data only (docs/synthetic-data.md): the command that created
    # this synthetic account ("seed-demo"); None for every real account.
    synthetic_source: Mapped[str | None] = mapped_column(String(32), index=True)


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
    # For You (ADR 0010): learn from what the listener does in the app. Off means
    # no interaction events are stored and the feed uses explicit signals only.
    personalize: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
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


class LinkedAccount(Base):
    """A listening service a user linked (ADR 0006). Tokens are ciphertext, never plain."""

    __tablename__ = "linked_accounts"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    external_user: Mapped[str] = mapped_column(String(256))
    token_ciphertext: Mapped[str] = mapped_column(Text)
    refresh_ciphertext: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # ACTIVE | NEEDS_RELINK
    cursor: Mapped[str | None] = mapped_column(Text)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(256))
    unmatched_plays: Mapped[int] = mapped_column(Integer, default=0)


class ListeningTally(Base):
    """Plays of one catalog artist from one linked account: the only listening data kept."""

    __tablename__ = "listening_tallies"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    artist_id: Mapped[str] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    plays: Mapped[int] = mapped_column(Integer)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthFlow(Base):
    """A linking flow in progress: single use, bound to the session that started it."""

    __tablename__ = "oauth_flows"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    verifier_ciphertext: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SocialProfile(Base):
    """The name a user shows to friends (R2-7). Chosen by the user, never from Firebase."""

    __tablename__ = "social_profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(40))
    # Opt-in (off by default): friends may see the user's top artists in friend paths.
    share_top_artists: Mapped[bool] = mapped_column(Boolean, default=False)
    update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FriendInvite(Base):
    """A single-use invite code. Only the SHA-256 of the code is stored."""

    __tablename__ = "friend_invites"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Friendship(Base):
    """One direction of a friendship; every friendship is stored as two rows."""

    __tablename__ = "friendships"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    friend_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserBlock(Base):
    """A person a user blocked: silent, and both stop seeing each other."""

    __tablename__ = "user_blocks"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Share(Base):
    """An artist, song, comparison or path one friend sent another, with an optional note."""

    __tablename__ = "shares"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    subjects: Mapped[list[str]] = mapped_column(JsonType)  # resource names
    note: Mapped[str] = mapped_column(String(140), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AbuseReport(Base):
    """A report for moderators. Keeps a copy of the reported note; purged after 90 days."""

    __tablename__ = "abuse_reports"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reported_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[str] = mapped_column(String(32))
    details: Mapped[str] = mapped_column(String(500), default="")
    share_kind: Mapped[str | None] = mapped_column(String(32))
    share_subjects: Mapped[list[str] | None] = mapped_column(JsonType)
    share_note: Mapped[str | None] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | REVIEWED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


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


# ---------------------------------------------------------------------------
# Around you (communities): opt-in campus and city membership, cached charts.
# ---------------------------------------------------------------------------


class CommunityMembership(Base):
    """A listener's opt-in to one campus or one city (at most one of each).

    The community ID is a slug from the curated directory, not a foreign key:
    the directory is a checked-in data file. ``synthetic`` marks development
    demo members created by ``songnexus seed-community``, so they can be removed.
    """

    __tablename__ = "community_memberships"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)  # CAMPUS | CITY
    community_id: Mapped[str] = mapped_column(String(128), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class CommunityChart(Base):
    """A computed community chart: aggregates only, already past the privacy floors.

    The newest row is the cached chart; one row per day is kept for 35 days so
    movement and rising can compare against earlier weeks.
    """

    __tablename__ = "community_charts"

    community_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)


# ---------------------------------------------------------------------------
# Game scores (ADR 0010): opt-in, one per player per game per day.
# ---------------------------------------------------------------------------


class GameScore(Base):
    """A score a signed-in player chose to submit, computed by the server from their play.

    ``campus_id`` is the campus the player belonged to when submitting; a score
    counts for a campus only while the player is still a member of it.
    """

    __tablename__ = "game_scores"
    __table_args__ = (Index("ix_game_scores_game_day", "game", "day"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    game: Mapped[str] = mapped_column(String(16), primary_key=True)  # PUZZLE | TRIVIA
    day: Mapped[str] = mapped_column(DATE, primary_key=True)  # the player's local date
    points: Mapped[int] = mapped_column(Integer)
    detail: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    campus_id: Mapped[str | None] = mapped_column(String(128))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TriviaAnswer(Base):
    """Whether a signed-in player's first answer to a Credit check question was right.

    The first answer counts: checking an answer reveals the right one, so a later
    score submission cannot replace it. Kept two days, then purged.
    """

    __tablename__ = "trivia_answers"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[str] = mapped_column(DATE, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    correct: Mapped[bool] = mapped_column(Boolean)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


# ---------------------------------------------------------------------------
# For You and Z-star (ADR 0010). Personal data: exported and deleted with the
# account; raw events are kept 180 days, served feeds 30 days.
# ---------------------------------------------------------------------------


class ArtistFollow(Base):
    """An artist a listener follows (added to their artists)."""

    __tablename__ = "artist_follows"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Not a foreign key: follows survive catalog rebuilds that drop an artist.
    artist_id: Mapped[str] = mapped_column(ID, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TasteFeedback(Base):
    """Explicit feedback on recommendations: "not interested", "more like this", "less of".

    ``subject`` is ``artists/{id}`` (NOT_INTERESTED, MORE_LIKE_THIS) or
    ``genres/{id}`` (LESS_OF_GENRE). Pressing it again refreshes ``created_at``.
    """

    __tablename__ = "taste_feedback"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str] = mapped_column(String(160), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InteractionEvent(Base):
    """One thing a listener did with an artist (impression, open, listen, skip, hide, share).

    ``event_id`` is chosen by the client, so a retried batch is stored once.
    Only signed-in listeners with personalization on are logged.
    """

    __tablename__ = "interaction_events"
    __table_args__ = (
        Index("ix_interaction_events_user_time", "user_id", "created_at"),
        Index("ix_interaction_events_feed", "feed_id", "artist_id"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    artist_id: Mapped[str] = mapped_column(ID)
    surface: Mapped[str] = mapped_column(String(24))
    feed_id: Mapped[str | None] = mapped_column(String(36))
    position: Mapped[int | None] = mapped_column(Integer)
    dwell_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FeedRequest(Base):
    """A served For You feed: which model and experiment arm made it."""

    __tablename__ = "feed_requests"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    catalog_version: Mapped[str] = mapped_column(String(128))
    model_version: Mapped[str] = mapped_column(String(64))
    arm: Mapped[str] = mapped_column(String(32))
    candidates: Mapped[int] = mapped_column(Integer)
    cold: Mapped[bool] = mapped_column(Boolean)


class FeedItem(Base):
    """One card of a served feed, with exactly the features the ranker saw (for training)."""

    __tablename__ = "feed_items"

    feed_id: Mapped[str] = mapped_column(
        ForeignKey("feed_requests.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[str] = mapped_column(ID)
    value: Mapped[float] = mapped_column(Float)
    sources: Mapped[list[str]] = mapped_column(JsonType, default=list)
    reason: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    features: Mapped[dict[str, float]] = mapped_column(JsonType, default=dict)
    heads: Mapped[dict[str, float]] = mapped_column(JsonType, default=dict)
    exploratory: Mapped[bool] = mapped_column(Boolean)


class ZstarArtifact(Base):
    """A stored Z-star artifact: artist embeddings for a catalog version, or a ranking model.

    One ``ranker`` row is ``active`` at a time; the service serves it.
    """

    __tablename__ = "zstar_artifacts"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # "<kind>:<version>"
    kind: Mapped[str] = mapped_column(String(16), index=True)  # embeddings | ranker
    version: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
