"""matches and match_members

Revision ID: 005_matches
Revises: 004_queue_entries
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_matches"
down_revision: Union[str, None] = "004_queue_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REQUIRED_ROLES = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")


def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("game", sa.String(length=20), server_default="lol", nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("accept_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "match_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("tier_rank", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(length=20), nullable=False),
        sa.Column("play_styles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("assigned_role", sa.String(length=20), nullable=False),
        sa.Column("accept_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "user_id", name="uq_match_members_match_user"),
        sa.UniqueConstraint("match_id", "assigned_role", name="uq_match_members_match_role"),
    )
    op.create_index(op.f("ix_match_members_match_id"), "match_members", ["match_id"], unique=False)
    op.create_index(op.f("ix_match_members_user_id"), "match_members", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_match_members_user_id"), table_name="match_members")
    op.drop_index(op.f("ix_match_members_match_id"), table_name="match_members")
    op.drop_table("match_members")
    op.drop_table("matches")