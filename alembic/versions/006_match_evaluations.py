"""match evaluations and match completed_at

Revision ID: 006_match_evaluations
Revises: 005_matches
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_match_evaluations"
down_revision: Union[str, None] = "005_matches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("matches", sa.Column("completed_by_user_id", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("evaluation_deadline", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_matches_completed_by_user_id_users",
        "matches",
        "users",
        ["completed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "match_evaluations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("evaluator_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("manner_delta", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluator_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_id",
            "evaluator_user_id",
            "target_user_id",
            name="uq_match_eval_evaluator_target",
        ),
        sa.CheckConstraint(
            "manner_delta >= -1 AND manner_delta <= 1",
            name="ck_match_evaluations_manner_delta",
        ),
        sa.CheckConstraint(
            "evaluator_user_id <> target_user_id",
            name="ck_match_evaluations_not_self",
        ),
    )
    op.create_index(
        op.f("ix_match_evaluations_match_id"), "match_evaluations", ["match_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_match_evaluations_match_id"), table_name="match_evaluations")
    op.drop_table("match_evaluations")
    op.drop_constraint("fk_matches_completed_by_user_id_users", "matches", type_="foreignkey")
    op.drop_column("matches", "evaluation_deadline")
    op.drop_column("matches", "completed_by_user_id")
    op.drop_column("matches", "completed_at")