"""lol profile

Revision ID: 003_lol_profile
Revises: 002_email_verfication
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_lol_profile"
down_revision: Union[str, None] = "002_email_verfication"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("discord_id", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("department", sa.String(length=50), nullable=False, server_default=""))
    op.add_column(
        "users",
        sa.Column("voice_chat_enable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("manner_score", sa.Float(), server_default=sa.text("3.0"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("college", sa.String(length=50), nullable=False, server_default=""),
    )

    op.create_table(
        "lol_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("primary_position", sa.String(length=10), nullable=False),
        sa.Column("secondary_position", sa.String(length=10), nullable=False),
        sa.Column("play_styles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_lol_profiles_user_id"), "lol_profiles", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_lol_profiles_user_id"), table_name="lol_profiles")
    op.drop_table("lol_profiles")
    op.drop_column("users", "manner_score")
    op.drop_column("users", "voice_chat_enable")
    op.drop_column("users", "department")
    op.drop_column("users", "discord_id")