"""Campus leaderboards and friend paths: game scores, first trivia answers, sharing opt-in.

Also marks synthetic development accounts (``users.synthetic_source``) so demo data
can be told apart from real accounts and removed (docs/synthetic-data.md).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("synthetic_source", sa.String(length=32), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_users_synthetic_source"), ["synthetic_source"], unique=False
        )

    with op.batch_alter_table("social_profiles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("share_top_artists", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    op.create_table(
        "game_scores",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("game", sa.String(length=16), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column(
            "detail",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("campus_id", sa.String(length=128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_game_scores_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "game", "day", name=op.f("pk_game_scores")),
    )
    with op.batch_alter_table("game_scores", schema=None) as batch_op:
        batch_op.create_index("ix_game_scores_game_day", ["game", "day"], unique=False)

    op.create_table(
        "trivia_answers",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("question_id", sa.String(length=8), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_trivia_answers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "day", "question_id", name=op.f("pk_trivia_answers")),
    )
    with op.batch_alter_table("trivia_answers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_trivia_answers_answered_at"), ["answered_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("trivia_answers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_trivia_answers_answered_at"))
    op.drop_table("trivia_answers")

    with op.batch_alter_table("game_scores", schema=None) as batch_op:
        batch_op.drop_index("ix_game_scores_game_day")
    op.drop_table("game_scores")

    with op.batch_alter_table("social_profiles", schema=None) as batch_op:
        batch_op.drop_column("share_top_artists")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_synthetic_source"))
        batch_op.drop_column("synthetic_source")
