"""align ORM constraints and Riot ranking fields

Revision ID: 008_schema_alignment
Revises: 007_lol_ranking
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_schema_alignment"
down_revision: Union[str, None] = "007_lol_ranking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lol_profiles", sa.Column("rank_division", sa.String(length=5), nullable=True)
    )
    op.add_column(
        "lol_profiles", sa.Column("league_points", sa.Integer(), nullable=True)
    )
    op.add_column(
        "queue_entries",
        sa.Column(
            "secondary_position",
            sa.String(length=20),
            server_default="ANYTHING",
            nullable=False,
        ),
    )
    op.add_column(
        "match_evaluations",
        sa.Column("is_auto", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # Older revisions created both a unique constraint and a redundant unique index.
    op.drop_index("ix_lol_profiles_user_id", table_name="lol_profiles")
    op.drop_index("ix_queue_entries_user_id", table_name="queue_entries")

    # A Riot account can belong to only one local profile. Keep the oldest owner if
    # legacy data contains duplicates, and require users to resync the others.
    op.execute(
        """
        WITH duplicates AS (
            SELECT id,
                   row_number() OVER (PARTITION BY puuid ORDER BY id) AS duplicate_no
            FROM lol_profiles
            WHERE puuid IS NOT NULL
        )
        UPDATE lol_profiles
        SET puuid = NULL,
            riot_id = NULL,
            tier = 'UN_RANKED',
            tier_rank = 0,
            rank_division = NULL,
            league_points = NULL,
            tier_updated_at = NULL
        WHERE id IN (
            SELECT id FROM duplicates WHERE duplicate_no > 1
        )
        """
    )
    op.create_index(
        "uq_lol_profiles_puuid",
        "lol_profiles",
        ["puuid"],
        unique=True,
        postgresql_where=sa.text("puuid IS NOT NULL"),
    )
    op.create_index(
        "ix_queue_entries_game_status_joined",
        "queue_entries",
        ["game", "status", "joined_at"],
        unique=False,
    )
    op.create_index(
        "ix_match_evaluations_evaluator_user_id",
        "match_evaluations",
        ["evaluator_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_match_evaluations_target_user_id",
        "match_evaluations",
        ["target_user_id"],
        unique=False,
    )

    op.create_check_constraint(
        "ck_queue_entries_status",
        "queue_entries",
        "status IN ('waiting', 'matched')",
    )
    op.create_check_constraint(
        "ck_matches_status",
        "matches",
        "status IN ('pending_accept', 'confirmed', 'cancelled', 'completed')",
    )
    op.create_check_constraint(
        "ck_match_members_accept_status",
        "match_members",
        "accept_status IN ('pending', 'accepted', 'declined')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_match_members_accept_status", "match_members", type_="check"
    )
    op.drop_constraint("ck_matches_status", "matches", type_="check")
    op.drop_constraint("ck_queue_entries_status", "queue_entries", type_="check")
    op.drop_index(
        "ix_match_evaluations_target_user_id", table_name="match_evaluations"
    )
    op.drop_index(
        "ix_match_evaluations_evaluator_user_id", table_name="match_evaluations"
    )
    op.drop_index(
        "ix_queue_entries_game_status_joined", table_name="queue_entries"
    )
    op.drop_index("uq_lol_profiles_puuid", table_name="lol_profiles")
    op.create_index(
        "ix_queue_entries_user_id",
        "queue_entries",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        "ix_lol_profiles_user_id",
        "lol_profiles",
        ["user_id"],
        unique=True,
    )
    op.drop_column("match_evaluations", "is_auto")
    op.drop_column("queue_entries", "secondary_position")
    op.drop_column("lol_profiles", "league_points")
    op.drop_column("lol_profiles", "rank_division")
