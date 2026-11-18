"""For You (ADR 0010): follows, taste feedback, interaction events, served feeds, Z-star artifacts.

Also adds ``preferences.personalize`` (learn from activity; on by default).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
    )


def upgrade() -> None:
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("personalize", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    op.create_table(
        "artist_follows",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _user_fk("artist_follows"),
        sa.PrimaryKeyConstraint("user_id", "artist_id", name=op.f("pk_artist_follows")),
    )

    op.create_table(
        "taste_feedback",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _user_fk("taste_feedback"),
        sa.PrimaryKeyConstraint("user_id", "subject", "kind", name=op.f("pk_taste_feedback")),
    )

    op.create_table(
        "interaction_events",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("surface", sa.String(length=24), nullable=False),
        sa.Column("feed_id", sa.String(length=36), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("dwell_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _user_fk("interaction_events"),
        sa.PrimaryKeyConstraint("user_id", "event_id", name=op.f("pk_interaction_events")),
    )
    with op.batch_alter_table("interaction_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_interaction_events_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            "ix_interaction_events_user_time", ["user_id", "created_at"], unique=False
        )
        batch_op.create_index("ix_interaction_events_feed", ["feed_id", "artist_id"], unique=False)

    op.create_table(
        "feed_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("catalog_version", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("arm", sa.String(length=32), nullable=False),
        sa.Column("candidates", sa.Integer(), nullable=False),
        sa.Column("cold", sa.Boolean(), nullable=False),
        _user_fk("feed_requests"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_requests")),
    )
    with op.batch_alter_table("feed_requests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_feed_requests_user_id"), ["user_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_feed_requests_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "feed_items",
        sa.Column("feed_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("sources", JSON, nullable=False),
        sa.Column("reason", JSON, nullable=False),
        sa.Column("features", JSON, nullable=False),
        sa.Column("heads", JSON, nullable=False),
        sa.Column("exploratory", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["feed_id"],
            ["feed_requests.id"],
            name=op.f("fk_feed_items_feed_id_feed_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feed_id", "position", name=op.f("pk_feed_items")),
    )

    op.create_table(
        "zstar_artifacts",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("metrics", JSON, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zstar_artifacts")),
    )
    with op.batch_alter_table("zstar_artifacts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_zstar_artifacts_kind"), ["kind"], unique=False)


def downgrade() -> None:
    op.drop_table("zstar_artifacts")
    op.drop_table("feed_items")
    op.drop_table("feed_requests")
    op.drop_table("interaction_events")
    op.drop_table("taste_feedback")
    op.drop_table("artist_follows")
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.drop_column("personalize")
