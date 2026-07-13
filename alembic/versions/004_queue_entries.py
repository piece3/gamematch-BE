"""queue entries

Revision ID: 004_queue_entries
Revises: 003_lol_profile
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_queue_entries"
down_revision: Union[str, None] = "003_lol_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "queue_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("game", sa.String(length=20), server_default="lol", nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("tier_rank", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(length=20), nullable=False),
        sa.Column("play_styles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="waiting", nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_queue_entries_user_id"), "queue_entries", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_queue_entries_user_id"), table_name="queue_entries")
    op.drop_table("queue_entries")