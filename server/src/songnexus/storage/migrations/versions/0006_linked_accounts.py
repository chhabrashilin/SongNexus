"""Linked listening accounts, their tallies, and OAuth flows (R2-6, ADR 0006).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "linked_accounts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_user", sa.String(length=256), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_ciphertext", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=256), nullable=True),
        sa.Column("unmatched_plays", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_linked_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "provider", name=op.f("pk_linked_accounts")),
    )
    with op.batch_alter_table("linked_accounts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_linked_accounts_next_sync_after"), ["next_sync_after"], unique=False
        )

    op.create_table(
        "listening_tallies",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("plays", sa.Integer(), nullable=False),
        sa.Column("last_played_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_listening_tallies_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_listening_tallies_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "provider", "artist_id", name=op.f("pk_listening_tallies")
        ),
    )

    op.create_table(
        "oauth_flows",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_flows_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_oauth_flows")),
    )
    with op.batch_alter_table("oauth_flows", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_oauth_flows_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_flows_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("oauth_flows", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_oauth_flows_user_id"))
        batch_op.drop_index(batch_op.f("ix_oauth_flows_expires_at"))
    op.drop_table("oauth_flows")
    op.drop_table("listening_tallies")
    with op.batch_alter_table("linked_accounts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_linked_accounts_next_sync_after"))
    op.drop_table("linked_accounts")
