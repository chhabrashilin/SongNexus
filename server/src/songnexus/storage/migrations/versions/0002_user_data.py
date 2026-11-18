"""User data: accounts, sessions, preferences, blocks, profiles and the audit log.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 04:28:29.532911
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("firebase_uid", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("age_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("firebase_uid", name=op.f("uq_users_firebase_uid")),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_deleted_at"), ["deleted_at"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_user_id"), ["user_id"], unique=False)

    op.create_table(
        "blocked_artists",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_blocked_artists_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "artist_id", name=op.f("pk_blocked_artists")),
    )
    op.create_table(
        "preferences",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "genre_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "categories",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("theme", sa.String(length=16), nullable=False),
        sa.Column("etag", sa.String(length=32), nullable=False),
        sa.Column("update_time", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_preferences_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_preferences")),
    )
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "top_artist_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("etag", sa.String(length=32), nullable=False),
        sa.Column("update_time", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_profiles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_profiles")),
    )
    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_user_sessions")),
    )
    with op.batch_alter_table("user_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_user_sessions_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_user_sessions_user_id"), ["user_id"], unique=False)


def downgrade() -> None:

    with op.batch_alter_table("user_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_sessions_user_id"))
        batch_op.drop_index(batch_op.f("ix_user_sessions_expires_at"))

    op.drop_table("user_sessions")
    op.drop_table("profiles")
    op.drop_table("preferences")
    op.drop_table("blocked_artists")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_log_user_id"))

    op.drop_table("audit_log")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_deleted_at"))

    op.drop_table("users")
