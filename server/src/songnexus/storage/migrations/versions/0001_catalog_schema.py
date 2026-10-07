"""Catalog schema: sources, raw records, entities, facts and mappings.

Revision ID: 0001
Revises:
Create Date: 2026-10-07 03:48:58.047779
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("homepage", sa.String(length=256), nullable=False),
        sa.Column("license", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_sources")),
    )
    op.create_table(
        "genres",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_genres")),
        sa.UniqueConstraint("normalized_name", name=op.f("uq_genres_normalized_name")),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("pipeline_version", sa.String(length=32), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "stats",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_table(
        "artists",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("sort_name", sa.String(length=512), nullable=True),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("artist_type", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("disambiguation", sa.String(length=512), nullable=True),
        sa.Column("begin_date", sa.String(length=10), nullable=True),
        sa.Column("end_date", sa.String(length=10), nullable=True),
        sa.Column("detail_level", sa.String(length=8), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_artists_ingestion_run_id_ingestion_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artists")),
    )
    with op.batch_alter_table("artists", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artists_normalized_name"), ["normalized_name"], unique=False
        )

    op.create_table(
        "entity_source_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.String(length=128), nullable=False),
        sa.Column("match_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_entity_source_mappings_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_entity_source_mappings_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_source_mappings")),
        sa.UniqueConstraint(
            "source_id",
            "entity_type",
            "source_entity_id",
            name=op.f("uq_entity_source_mappings_source_id"),
        ),
    )
    with op.batch_alter_table("entity_source_mappings", schema=None) as batch_op:
        batch_op.create_index(
            "ix_entity_source_mappings_entity", ["entity_type", "entity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_entity_source_mappings_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "labels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("label_type", sa.String(length=64), nullable=True),
        sa.Column("disambiguation", sa.String(length=512), nullable=True),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_labels_ingestion_run_id_ingestion_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labels")),
    )
    with op.batch_alter_table("labels", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_labels_normalized_name"), ["normalized_name"], unique=False
        )

    op.create_table(
        "raw_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("request_key", sa.String(length=1024), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("retrieved_at", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("last_seen_run_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_raw_records_last_seen_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], name=op.f("fk_raw_records_source_id_data_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_records")),
        sa.UniqueConstraint("source_id", "request_key", name=op.f("uq_raw_records_source_id")),
    )
    op.create_table(
        "recordings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("length_ms", sa.Integer(), nullable=True),
        sa.Column("first_release_date", sa.String(length=10), nullable=True),
        sa.Column("dedup_key", sa.String(length=2048), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_recordings_ingestion_run_id_ingestion_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recordings")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_recordings_dedup_key")),
    )
    with op.batch_alter_table("recordings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_recordings_normalized_title"), ["normalized_title"], unique=False
        )

    op.create_table(
        "releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("primary_type", sa.String(length=32), nullable=True),
        sa.Column("first_release_date", sa.String(length=10), nullable=True),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_releases_ingestion_run_id_ingestion_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_releases")),
    )
    with op.batch_alter_table("releases", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_releases_normalized_title"), ["normalized_title"], unique=False
        )

    op.create_table(
        "artist_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_aliases_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_artist_aliases_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_artist_aliases_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_artist_aliases_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artist_aliases")),
        sa.UniqueConstraint(
            "artist_id", "normalized_alias", name=op.f("uq_artist_aliases_artist_id")
        ),
    )
    with op.batch_alter_table("artist_aliases", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artist_aliases_artist_id"), ["artist_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_artist_aliases_normalized_alias"), ["normalized_alias"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_artist_aliases_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "artist_genres",
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("genre_id", sa.String(length=36), nullable=False),
        sa.Column("votes", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_genres_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["genre_id"], ["genres.id"], name=op.f("fk_artist_genres_genre_id_genres")
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_artist_genres_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_artist_genres_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], name=op.f("fk_artist_genres_source_id_data_sources")
        ),
        sa.PrimaryKeyConstraint("artist_id", "genre_id", name=op.f("pk_artist_genres")),
    )
    with op.batch_alter_table("artist_genres", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_artist_genres_genre_id"), ["genre_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_artist_genres_source_id"), ["source_id"], unique=False)

    op.create_table(
        "artist_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_links_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_artist_links_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_artist_links_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], name=op.f("fk_artist_links_source_id_data_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artist_links")),
        sa.UniqueConstraint("artist_id", "url", name=op.f("uq_artist_links_artist_id")),
    )
    with op.batch_alter_table("artist_links", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_artist_links_artist_id"), ["artist_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_artist_links_source_id"), ["source_id"], unique=False)

    op.create_table(
        "artist_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_artist_id", sa.String(length=36), nullable=False),
        sa.Column("object_artist_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column(
            "attributes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("begin_date", sa.String(length=10), nullable=True),
        sa.Column("end_date", sa.String(length=10), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_artist_relations_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["object_artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_relations_object_artist_id_artists"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_artist_relations_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_artist_relations_source_id_data_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_relations_subject_artist_id_artists"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artist_relations")),
        sa.UniqueConstraint(
            "subject_artist_id",
            "object_artist_id",
            "relation_type",
            name=op.f("uq_artist_relations_subject_artist_id"),
        ),
    )
    with op.batch_alter_table("artist_relations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artist_relations_object_artist_id"), ["object_artist_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_artist_relations_source_id"), ["source_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_artist_relations_subject_artist_id"), ["subject_artist_id"], unique=False
        )

    op.create_table(
        "recording_credits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recording_id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("role_detail", sa.String(length=256), nullable=False),
        sa.Column("credited_as", sa.String(length=512), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"], ["artists.id"], name=op.f("fk_recording_credits_artist_id_artists")
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_recording_credits_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_recording_credits_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["recordings.id"],
            name=op.f("fk_recording_credits_recording_id_recordings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_recording_credits_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recording_credits")),
        sa.UniqueConstraint(
            "recording_id",
            "artist_id",
            "role",
            "role_detail",
            name=op.f("uq_recording_credits_recording_id"),
        ),
    )
    with op.batch_alter_table("recording_credits", schema=None) as batch_op:
        batch_op.create_index(
            "ix_recording_credits_artist_role", ["artist_id", "role"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_recording_credits_recording_id"), ["recording_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_recording_credits_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "release_artists",
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("credited_as", sa.String(length=512), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"], ["artists.id"], name=op.f("fk_release_artists_artist_id_artists")
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_release_artists_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_release_artists_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_release_artists_release_id_releases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_release_artists_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("release_id", "artist_id", name=op.f("pk_release_artists")),
    )
    with op.batch_alter_table("release_artists", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_release_artists_artist_id"), ["artist_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_release_artists_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "release_credits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("role_detail", sa.String(length=256), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"], ["artists.id"], name=op.f("fk_release_credits_artist_id_artists")
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_release_credits_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_release_credits_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_release_credits_release_id_releases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_release_credits_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_credits")),
        sa.UniqueConstraint(
            "release_id",
            "artist_id",
            "role",
            "role_detail",
            name=op.f("uq_release_credits_release_id"),
        ),
    )
    with op.batch_alter_table("release_credits", schema=None) as batch_op:
        batch_op.create_index("ix_release_credits_artist_role", ["artist_id", "role"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_release_credits_release_id"), ["release_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_release_credits_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "release_labels",
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("label_id", sa.String(length=36), nullable=False),
        sa.Column("catalog_number", sa.String(length=128), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_release_labels_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["label_id"], ["labels.id"], name=op.f("fk_release_labels_label_id_labels")
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_release_labels_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_release_labels_release_id_releases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_release_labels_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("release_id", "label_id", name=op.f("pk_release_labels")),
    )
    with op.batch_alter_table("release_labels", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_release_labels_label_id"), ["label_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_release_labels_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "release_recordings",
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("disc_number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_release_recordings_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_release_recordings_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["recordings.id"],
            name=op.f("fk_release_recordings_recording_id_recordings"),
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_release_recordings_release_id_releases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_release_recordings_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint(
            "release_id", "disc_number", "position", name=op.f("pk_release_recordings")
        ),
    )
    with op.batch_alter_table("release_recordings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_release_recordings_recording_id"), ["recording_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_release_recordings_source_id"), ["source_id"], unique=False
        )


def downgrade() -> None:

    with op.batch_alter_table("release_recordings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_recordings_source_id"))
        batch_op.drop_index(batch_op.f("ix_release_recordings_recording_id"))

    op.drop_table("release_recordings")
    with op.batch_alter_table("release_labels", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_labels_source_id"))
        batch_op.drop_index(batch_op.f("ix_release_labels_label_id"))

    op.drop_table("release_labels")
    with op.batch_alter_table("release_credits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_credits_source_id"))
        batch_op.drop_index(batch_op.f("ix_release_credits_release_id"))
        batch_op.drop_index("ix_release_credits_artist_role")

    op.drop_table("release_credits")
    with op.batch_alter_table("release_artists", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_artists_source_id"))
        batch_op.drop_index(batch_op.f("ix_release_artists_artist_id"))

    op.drop_table("release_artists")
    with op.batch_alter_table("recording_credits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recording_credits_source_id"))
        batch_op.drop_index(batch_op.f("ix_recording_credits_recording_id"))
        batch_op.drop_index("ix_recording_credits_artist_role")

    op.drop_table("recording_credits")
    with op.batch_alter_table("artist_relations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artist_relations_subject_artist_id"))
        batch_op.drop_index(batch_op.f("ix_artist_relations_source_id"))
        batch_op.drop_index(batch_op.f("ix_artist_relations_object_artist_id"))

    op.drop_table("artist_relations")
    with op.batch_alter_table("artist_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artist_links_source_id"))
        batch_op.drop_index(batch_op.f("ix_artist_links_artist_id"))

    op.drop_table("artist_links")
    with op.batch_alter_table("artist_genres", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artist_genres_source_id"))
        batch_op.drop_index(batch_op.f("ix_artist_genres_genre_id"))

    op.drop_table("artist_genres")
    with op.batch_alter_table("artist_aliases", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artist_aliases_source_id"))
        batch_op.drop_index(batch_op.f("ix_artist_aliases_normalized_alias"))
        batch_op.drop_index(batch_op.f("ix_artist_aliases_artist_id"))

    op.drop_table("artist_aliases")
    with op.batch_alter_table("releases", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_releases_normalized_title"))

    op.drop_table("releases")
    with op.batch_alter_table("recordings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recordings_normalized_title"))

    op.drop_table("recordings")
    op.drop_table("raw_records")
    with op.batch_alter_table("labels", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_labels_normalized_name"))

    op.drop_table("labels")
    with op.batch_alter_table("entity_source_mappings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_entity_source_mappings_source_id"))
        batch_op.drop_index("ix_entity_source_mappings_entity")

    op.drop_table("entity_source_mappings")
    with op.batch_alter_table("artists", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artists_normalized_name"))

    op.drop_table("artists")
    op.drop_table("ingestion_runs")
    op.drop_table("genres")
    op.drop_table("data_sources")
