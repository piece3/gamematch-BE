"""remove legacy manually assigned tiers

Revision ID: 009_riot_only_tiers
Revises: 008_schema_alignment
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_riot_only_tiers"
down_revision: Union[str, None] = "008_schema_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE lol_profiles
            SET tier = 'UN_RANKED',
                tier_rank = 0,
                rank_division = NULL,
                league_points = NULL,
                tier_updated_at = NULL
            WHERE puuid IS NULL
            """
        )
    )


def downgrade() -> None:
    # Legacy manual tiers cannot be reconstructed safely.
    pass
