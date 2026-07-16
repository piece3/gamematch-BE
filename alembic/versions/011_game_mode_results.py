"""game modes and personal match result history

Revision ID: 011_game_mode_results
Revises: 010_realign_queue_tiers
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_game_mode_results"
down_revision: Union[str, None] = "010_realign_queue_tiers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "queue_entries",
        sa.Column(
            "game_mode",
            sa.String(length=20),
            server_default="SOLO",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_queue_entries_game_mode",
        "queue_entries",
        "game_mode IN ('SOLO', 'FLEX', 'NORMAL')",
    )
    op.drop_index("ix_queue_entries_game_status_joined", table_name="queue_entries")
    op.create_index(
        "ix_queue_entries_game_mode_status_joined",
        "queue_entries",
        ["game", "game_mode", "status", "joined_at"],
        unique=False,
    )

    op.add_column(
        "matches",
        sa.Column(
            "game_mode",
            sa.String(length=20),
            server_default="SOLO",
            nullable=False,
        ),
    )
    op.add_column(
        "matches",
        sa.Column("riot_match_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column(
            "result_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_matches_game_mode",
        "matches",
        "game_mode IN ('SOLO', 'FLEX', 'NORMAL')",
    )
    op.create_check_constraint(
        "ck_matches_result_status",
        "matches",
        "result_status IN ('pending', 'synced', 'unresolved')",
    )

    op.create_table(
        "user_match_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("riot_match_id", sa.String(length=64), nullable=False),
        sa.Column("game_mode", sa.String(length=20), nullable=False),
        sa.Column("won", sa.Boolean(), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "riot_match_id",
            name="uq_user_match_records_user_riot",
        ),
        sa.CheckConstraint(
            "game_mode IN ('SOLO', 'FLEX', 'NORMAL')",
            name="ck_user_match_records_game_mode",
        ),
    )
    op.create_index(
        "ix_user_match_records_user_played_at",
        "user_match_records",
        ["user_id", "played_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_match_records_match_id"),
        "user_match_records",
        ["match_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_match_records_match_id"), table_name="user_match_records"
    )
    op.drop_index(
        "ix_user_match_records_user_played_at", table_name="user_match_records"
    )
    op.drop_table("user_match_records")
    op.drop_constraint("ck_matches_result_status", "matches", type_="check")
    op.drop_constraint("ck_matches_game_mode", "matches", type_="check")
    op.drop_column("matches", "result_status")
    op.drop_column("matches", "riot_match_id")
    op.drop_column("matches", "game_mode")
    op.drop_index(
        "ix_queue_entries_game_mode_status_joined", table_name="queue_entries"
    )
    op.create_index(
        "ix_queue_entries_game_status_joined",
        "queue_entries",
        ["game", "status", "joined_at"],
        unique=False,
    )
    op.drop_constraint("ck_queue_entries_game_mode", "queue_entries", type_="check")
    op.drop_column("queue_entries", "game_mode")
