"""Around you: opt-in campus and city memberships, cached community charts.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_charts",
        sa.Column("community_id", sa.String(length=128), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("community_id", "computed_at", name=op.f("pk_community_charts")),
    )
    with op.batch_alter_table("community_charts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_community_charts_computed_at"), ["computed_at"], unique=False
        )

    op.create_table(
        "community_memberships",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("community_id", sa.String(length=128), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_community_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "kind", name=op.f("pk_community_memberships")),
    )
    with op.batch_alter_table("community_memberships", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_community_memberships_community_id"), ["community_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("community_memberships", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_community_memberships_community_id"))

    op.drop_table("community_memberships")
    with op.batch_alter_table("community_charts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_community_charts_computed_at"))

    op.drop_table("community_charts")
