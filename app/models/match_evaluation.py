from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MatchEvaluation(Base):
    __tablename__ = "match_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "evaluator_user_id",
            "target_user_id",
            name="uq_match_eval_evaluator_target",
        ),
        CheckConstraint(
            "manner_delta >= -1 AND manner_delta <= 1",
            name="ck_match_evaluations_manner_delta",
        ),
        CheckConstraint(
            "evaluator_user_id <> target_user_id",
            name="ck_match_evaluations_not_self",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    evaluator_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    manner_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
