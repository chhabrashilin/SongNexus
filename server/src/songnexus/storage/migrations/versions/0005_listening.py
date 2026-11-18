"""Aggregate listening: artist audiences and co-listening (R2-5).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _provenance(table: str) -> list[Any]:
    return [
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f(f"fk_{table}_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f(f"fk_{table}_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], name=op.f(f"fk_{table}_source_id_data_sources")
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "artist_audiences",
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("listeners", sa.Integer(), nullable=False),
        sa.Column("listens", sa.Integer(), nullable=False),
        *_provenance("artist_audiences"),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_audiences_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("artist_id", "source_id", name=op.f("pk_artist_audiences")),
    )
    with op.batch_alter_table("artist_audiences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artist_audiences_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "artist_colistening",
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("other_artist_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        *_provenance("artist_colistening"),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_colistening_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["other_artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_colistening_other_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "artist_id", "other_artist_id", "source_id", name=op.f("pk_artist_colistening")
        ),
    )
    with op.batch_alter_table("artist_colistening", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artist_colistening_other_artist_id"), ["other_artist_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_artist_colistening_source_id"), ["source_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("artist_colistening", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artist_colistening_source_id"))
        batch_op.drop_index(batch_op.f("ix_artist_colistening_other_artist_id"))
    op.drop_table("artist_colistening")
    with op.batch_alter_table("artist_audiences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artist_audiences_source_id"))
    op.drop_table("artist_audiences")
