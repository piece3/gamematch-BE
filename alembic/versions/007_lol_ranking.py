"""lol profile ranking + riot fields

Revision ID: 007_lol_ranking
Revises: 006_match_evaluations
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_lol_ranking"
down_revision: Union[str, None] = "006_match_evaluations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RANKING_SCORE = {
    "UN_RANKED": 0,
    "IRON": 1,
    "BRONZE": 2,
    "SILVER": 3,
    "GOLD": 4,
    "PLATINUM": 5,
    "EMERALD": 6,
    "DIAMOND": 7,
    "MASTER": 8,
    "GRANDMASTER": 9,
    "CHALLENGER": 10,
}


def upgrade() -> None:
    op.add_column(
        "lol_profiles",
        sa.Column("tier_rank", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "lol_profiles",
        sa.Column("riot_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "lol_profiles",
        sa.Column("puuid", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "lol_profiles",
        sa.Column("tier_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_lol_profiles_tier_rank"),
        "lol_profiles",
        ["tier_rank"],
        unique=False,
    )

    conn = op.get_bind()
    for tier, score in RANKING_SCORE.items():
        conn.execute(
            sa.text("UPDATE lol_profiles SET tier_rank = :score WHERE tier = :tier"),
            {"score": score, "tier": tier},
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_lol_profiles_tier_rank"), table_name="lol_profiles")
    op.drop_column("lol_profiles", "tier_updated_at")
    op.drop_column("lol_profiles", "puuid")
    op.drop_column("lol_profiles", "riot_id")
    op.drop_column("lol_profiles", "tier_rank")
