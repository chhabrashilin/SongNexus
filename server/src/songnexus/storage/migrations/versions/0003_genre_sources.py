"""Genre associations per source, and the genre hierarchy (R2-1).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01

``artist_genres`` gains ``source_id`` in its primary key, so MusicBrainz and
Discogs can both assert the same artist-genre pair. ``genre_parents`` holds
the subgenre links from Wikidata.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("artist_genres", schema=None) as batch_op:
        batch_op.drop_constraint("pk_artist_genres", type_="primary")
        batch_op.create_primary_key("pk_artist_genres", ["artist_id", "genre_id", "source_id"])

    op.create_table(
        "genre_parents",
        sa.Column("genre_id", sa.String(length=36), nullable=False),
        sa.Column("parent_genre_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("raw_record_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["genre_id"],
            ["genres.id"],
            name=op.f("fk_genre_parents_genre_id_genres"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_genre_id"],
            ["genres.id"],
            name=op.f("fk_genre_parents_parent_genre_id_genres"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_genre_parents_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.id"],
            name=op.f("fk_genre_parents_raw_record_id_raw_records"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], name=op.f("fk_genre_parents_source_id_data_sources")
        ),
        sa.PrimaryKeyConstraint(
            "genre_id", "parent_genre_id", "source_id", name=op.f("pk_genre_parents")
        ),
    )
    with op.batch_alter_table("genre_parents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_genre_parents_parent_genre_id"), ["parent_genre_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_genre_parents_source_id"), ["source_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("genre_parents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_genre_parents_source_id"))
        batch_op.drop_index(batch_op.f("ix_genre_parents_parent_genre_id"))
    op.drop_table("genre_parents")

    # Associations from any source other than MusicBrainz cannot fit the old key.
    op.execute("DELETE FROM artist_genres WHERE source_id <> 'musicbrainz-supplementary'")
    with op.batch_alter_table("artist_genres", schema=None) as batch_op:
        batch_op.drop_constraint("pk_artist_genres", type_="primary")
        batch_op.create_primary_key("pk_artist_genres", ["artist_id", "genre_id"])
