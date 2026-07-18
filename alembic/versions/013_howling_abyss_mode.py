"""rename NORMAL game_mode to Howling Abyss

Revision ID: 013_howling_abyss_mode
Revises: 012_match_quick_messages
"""

from typing import Sequence, Union

from alembic import op

revision: str = "013_howling_abyss_mode"
down_revision: Union[str, None] = "012_match_quick_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = "('SOLO', 'FLEX', 'Howling Abyss')"
_OLD = "('SOLO', 'FLEX', 'NORMAL')"


def upgrade() -> None:
    op.drop_constraint("ck_queue_entries_game_mode", "queue_entries", type_="check")
    op.drop_constraint("ck_matches_game_mode", "matches", type_="check")
    op.drop_constraint(
        "ck_user_match_records_game_mode", "user_match_records", type_="check"
    )

    op.execute("UPDATE queue_entries SET game_mode = 'Howling Abyss' WHERE game_mode = 'NORMAL'")
    op.execute("UPDATE matches SET game_mode = 'Howling Abyss' WHERE game_mode = 'NORMAL'")
    op.execute(
        "UPDATE user_match_records SET game_mode = 'Howling Abyss' WHERE game_mode = 'NORMAL'"
    )

    op.create_check_constraint(
        "ck_queue_entries_game_mode",
        "queue_entries",
        f"game_mode IN {_NEW}",
    )
    op.create_check_constraint(
        "ck_matches_game_mode",
        "matches",
        f"game_mode IN {_NEW}",
    )
    op.create_check_constraint(
        "ck_user_match_records_game_mode",
        "user_match_records",
        f"game_mode IN {_NEW}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_queue_entries_game_mode", "queue_entries", type_="check")
    op.drop_constraint("ck_matches_game_mode", "matches", type_="check")
    op.drop_constraint(
        "ck_user_match_records_game_mode", "user_match_records", type_="check"
    )

    op.execute("UPDATE queue_entries SET game_mode = 'NORMAL' WHERE game_mode = 'Howling Abyss'")
    op.execute("UPDATE matches SET game_mode = 'NORMAL' WHERE game_mode = 'Howling Abyss'")
    op.execute(
        "UPDATE user_match_records SET game_mode = 'NORMAL' WHERE game_mode = 'Howling Abyss'"
    )

    op.create_check_constraint(
        "ck_queue_entries_game_mode",
        "queue_entries",
        f"game_mode IN {_OLD}",
    )
    op.create_check_constraint(
        "ck_matches_game_mode",
        "matches",
        f"game_mode IN {_OLD}",
    )
    op.create_check_constraint(
        "ck_user_match_records_game_mode",
        "user_match_records",
        f"game_mode IN {_OLD}",
    )
