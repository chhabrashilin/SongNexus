"""Friends and sharing: display names, invites, friendships, blocks, shares, reports (R2-7).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "abuse_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reporter_id", sa.String(length=36), nullable=False),
        sa.Column("reported_user_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("details", sa.String(length=500), nullable=False),
        sa.Column("share_kind", sa.String(length=32), nullable=True),
        sa.Column(
            "share_subjects",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("share_note", sa.String(length=140), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reported_user_id"],
            ["users.id"],
            name=op.f("fk_abuse_reports_reported_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name=op.f("fk_abuse_reports_reporter_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abuse_reports")),
    )
    with op.batch_alter_table("abuse_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_abuse_reports_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_abuse_reports_reported_user_id"), ["reported_user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_abuse_reports_reporter_id"), ["reporter_id"], unique=False
        )

    op.create_table(
        "friend_invites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_friend_invites_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_friend_invites")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_friend_invites_code_hash")),
    )
    with op.batch_alter_table("friend_invites", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_friend_invites_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_friend_invites_user_id"), ["user_id"], unique=False)

    op.create_table(
        "friendships",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("friend_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["friend_id"],
            ["users.id"],
            name=op.f("fk_friendships_friend_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_friendships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "friend_id", name=op.f("pk_friendships")),
    )
    with op.batch_alter_table("friendships", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_friendships_friend_id"), ["friend_id"], unique=False)

    op.create_table(
        "shares",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sender_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "subjects",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=140), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name=op.f("fk_shares_recipient_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name=op.f("fk_shares_sender_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shares")),
    )
    with op.batch_alter_table("shares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shares_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_shares_recipient_id"), ["recipient_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shares_sender_id"), ["sender_id"], unique=False)

    op.create_table(
        "social_profiles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column("update_time", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_social_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_social_profiles")),
    )
    op.create_table(
        "user_blocks",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("blocked_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["blocked_user_id"],
            ["users.id"],
            name=op.f("fk_user_blocks_blocked_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_blocks_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "blocked_user_id", name=op.f("pk_user_blocks")),
    )
    with op.batch_alter_table("user_blocks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_user_blocks_blocked_user_id"), ["blocked_user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("user_blocks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_blocks_blocked_user_id"))

    op.drop_table("user_blocks")
    op.drop_table("social_profiles")
    with op.batch_alter_table("shares", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shares_sender_id"))
        batch_op.drop_index(batch_op.f("ix_shares_recipient_id"))
        batch_op.drop_index(batch_op.f("ix_shares_created_at"))

    op.drop_table("shares")
    with op.batch_alter_table("friendships", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_friendships_friend_id"))

    op.drop_table("friendships")
    with op.batch_alter_table("friend_invites", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_friend_invites_user_id"))
        batch_op.drop_index(batch_op.f("ix_friend_invites_expires_at"))

    op.drop_table("friend_invites")
    with op.batch_alter_table("abuse_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_abuse_reports_reporter_id"))
        batch_op.drop_index(batch_op.f("ix_abuse_reports_reported_user_id"))
        batch_op.drop_index(batch_op.f("ix_abuse_reports_created_at"))

    op.drop_table("abuse_reports")
