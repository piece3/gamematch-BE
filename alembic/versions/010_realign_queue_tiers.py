"""realign queued tier snapshots with Riot-backed profiles

Revision ID: 010_realign_queue_tiers
Revises: 009_riot_only_tiers
"""

from typing import Sequence, Union

from alembic import op

revision: str = "010_realign_queue_tiers"
down_revision: Union[str, None] = "009_riot_only_tiers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE queue_entries AS queue
        SET tier = profile.tier,
            tier_rank = CASE profile.tier
                WHEN 'IRON' THEN 1
                WHEN 'BRONZE' THEN 2
                WHEN 'SILVER' THEN 3
                WHEN 'GOLD' THEN 4
                WHEN 'PLATINUM' THEN 5
                WHEN 'EMERALD' THEN 6
                WHEN 'DIAMOND' THEN 7
                WHEN 'MASTER' THEN 8
                WHEN 'GRANDMASTER' THEN 9
                WHEN 'CHALLENGER' THEN 10
                ELSE 3
            END
        FROM lol_profiles AS profile
        WHERE queue.user_id = profile.user_id
        """
    )


def downgrade() -> None:
    # Historical queue snapshots cannot be reconstructed safely.
    pass
