"""Artist photos: freely licensed Wikimedia Commons images found through Wikidata.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artist_images",
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("wikidata_id", sa.String(length=32), nullable=False),
        sa.Column("commons_file", sa.String(length=512), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=2048), nullable=False),
        sa.Column("large_url", sa.String(length=2048), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("author", sa.String(length=512), nullable=True),
        sa.Column("license", sa.String(length=128), nullable=False),
        sa.Column("license_url", sa.String(length=2048), nullable=True),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_images_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("artist_id", name=op.f("pk_artist_images")),
    )


def downgrade() -> None:
    op.drop_table("artist_images")
