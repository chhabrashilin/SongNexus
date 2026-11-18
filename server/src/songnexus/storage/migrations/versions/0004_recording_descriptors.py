"""Audio descriptors per recording, for song comparison (R2-4).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recording_descriptors",
        sa.Column("recording_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_recording_id", sa.String(length=64), nullable=False),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("key", sa.String(length=4), nullable=True),
        sa.Column("scale", sa.String(length=8), nullable=True),
        sa.Column("key_strength", sa.Float(), nullable=True),
        sa.Column("length_s", sa.Float(), nullable=True),
        sa.Column("average_loudness", sa.Float(), nullable=True),
        sa.Column("dynamic_complexity", sa.Float(), nullable=True),
        sa.Column(
            "moods",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_recording_descriptors_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_recording_descriptors_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["recordings.id"],
            name=op.f("fk_recording_descriptors_recording_id_recordings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_recording_descriptors_source_id_data_sources"),
        ),
        sa.PrimaryKeyConstraint("recording_id", "source_id", name=op.f("pk_recording_descriptors")),
    )
    with op.batch_alter_table("recording_descriptors", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_recording_descriptors_source_id"), ["source_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("recording_descriptors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recording_descriptors_source_id"))
    op.drop_table("recording_descriptors")
