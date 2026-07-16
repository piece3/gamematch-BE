from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MAX_RECORDS_PER_USER = 5


class UserMatchRecord(Base):
    """Personal win/loss history from a completed lobby match (max 5 per user)."""

    __tablename__ = "user_match_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "riot_match_id",
            name="uq_user_match_records_user_riot",
        ),
        CheckConstraint(
            "game_mode IN ('SOLO', 'FLEX', 'NORMAL')",
            name="ck_user_match_records_game_mode",
        ),
        Index(
            "ix_user_match_records_user_played_at",
            "user_id",
            "played_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    riot_match_id: Mapped[str] = mapped_column(String(64), nullable=False)
    game_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    won: Mapped[bool] = mapped_column(Boolean, nullable=False)
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
