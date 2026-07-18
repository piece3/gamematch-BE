"""add FC Online profiles, records, and matchmaking modes

Revision ID: 014_fc_online_matching
Revises: 013_howling_abyss_mode
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_fc_online_matching"
down_revision: Union[str, None] = "013_howling_abyss_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "queue_entries",
        sa.Column("party_size", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "matches",
        sa.Column("party_size", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "matches",
        sa.Column("nexon_match_id", sa.String(length=64), nullable=True),
    )
    op.alter_column(
        "queue_entries",
        "tier",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "match_members",
        "tier",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

    op.drop_constraint("ck_queue_entries_game_mode", "queue_entries", type_="check")
    op.drop_constraint("ck_matches_game_mode", "matches", type_="check")
    game_mode_check = (
        "(game = 'lol' AND game_mode IN ('SOLO', 'FLEX', 'Howling Abyss')) "
        "OR (game = 'fc_online' AND game_mode IN ('OFFICIAL_1V1', 'OFFICIAL_2V2'))"
    )
    party_size_check = (
        "(game = 'lol' AND party_size = 1) "
        "OR (game_mode = 'OFFICIAL_1V1' AND party_size = 1) "
        "OR (game_mode = 'OFFICIAL_2V2' AND party_size = 2)"
    )
    op.create_check_constraint(
        "ck_queue_entries_game_mode", "queue_entries", game_mode_check
    )
    op.create_check_constraint(
        "ck_matches_game_mode", "matches", game_mode_check
    )
    op.create_check_constraint(
        "ck_queue_entries_party_size", "queue_entries", party_size_check
    )
    op.create_check_constraint(
        "ck_matches_party_size", "matches", party_size_check
    )

    op.create_table(
        "fc_online_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(length=50), nullable=False),
        sa.Column("ouid", sa.String(length=80), nullable=False),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("division_1v1_id", sa.Integer(), nullable=True),
        sa.Column("division_1v1_name", sa.String(length=80), nullable=True),
        sa.Column("division_1v1_rank", sa.Integer(), nullable=True),
        sa.Column("division_2v2_id", sa.Integer(), nullable=True),
        sa.Column("division_2v2_name", sa.String(length=80), nullable=True),
        sa.Column("division_2v2_rank", sa.Integer(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ouid"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_fc_online_profiles_division_1v1_rank"),
        "fc_online_profiles",
        ["division_1v1_rank"],
    )
    op.create_index(
        op.f("ix_fc_online_profiles_division_2v2_rank"),
        "fc_online_profiles",
        ["division_2v2_rank"],
    )

    op.create_table(
        "fc_online_match_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("nexon_match_id", sa.String(length=64), nullable=False),
        sa.Column("game_mode", sa.String(length=20), nullable=False),
        sa.Column("result", sa.String(length=4), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('WIN', 'DRAW', 'LOSS')",
            name="ck_fc_online_records_result",
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "nexon_match_id",
            name="uq_fc_online_records_user_nexon",
        ),
    )
    op.create_index(
        "ix_fc_online_records_user_played_at",
        "fc_online_match_records",
        ["user_id", "played_at"],
    )
    op.create_index(
        op.f("ix_fc_online_match_records_match_id"),
        "fc_online_match_records",
        ["match_id"],
    )


def downgrade() -> None:
    op.drop_table("fc_online_match_records")
    op.drop_table("fc_online_profiles")
    op.execute("DELETE FROM queue_entries WHERE game = 'fc_online'")
    op.execute("DELETE FROM matches WHERE game = 'fc_online'")

    op.drop_constraint("ck_queue_entries_party_size", "queue_entries", type_="check")
    op.drop_constraint("ck_matches_party_size", "matches", type_="check")
    op.drop_constraint("ck_queue_entries_game_mode", "queue_entries", type_="check")
    op.drop_constraint("ck_matches_game_mode", "matches", type_="check")
    old_check = "game_mode IN ('SOLO', 'FLEX', 'Howling Abyss')"
    op.create_check_constraint(
        "ck_queue_entries_game_mode", "queue_entries", old_check
    )
    op.create_check_constraint("ck_matches_game_mode", "matches", old_check)

    op.alter_column(
        "match_members",
        "tier",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "queue_entries",
        "tier",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.drop_column("matches", "nexon_match_id")
    op.drop_column("matches", "party_size")
    op.drop_column("queue_entries", "party_size")
