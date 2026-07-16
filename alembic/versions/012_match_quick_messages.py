"""add preset quick messages for matched users

Revision ID: 012_match_quick_messages
Revises: 011_game_mode_results
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_match_quick_messages"
down_revision: Union[str, None] = "011_game_mode_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "match_quick_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_match_quick_messages_match_id"),
        "match_quick_messages",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_quick_messages_user_id"),
        "match_quick_messages",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_match_quick_messages_user_id"),
        table_name="match_quick_messages",
    )
    op.drop_index(
        op.f("ix_match_quick_messages_match_id"),
        table_name="match_quick_messages",
    )
    op.drop_table("match_quick_messages")
