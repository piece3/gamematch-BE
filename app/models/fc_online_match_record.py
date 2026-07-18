from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MAX_RECORDS_PER_USER = 5
MAX_FC_ONLINE_RECORDS_PER_USER = MAX_RECORDS_PER_USER


class FcOnlineMatchRecord(Base):
    __tablename__ = "fc_online_match_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "nexon_match_id",
            name="uq_fc_online_records_user_nexon",
        ),
        CheckConstraint(
            "result IN ('WIN', 'DRAW', 'LOSS')",
            name="ck_fc_online_records_result",
        ),
        Index(
            "ix_fc_online_records_user_played_at",
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
    nexon_match_id: Mapped[str] = mapped_column(String(64), nullable=False)
    game_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[str] = mapped_column(String(4), nullable=False)
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
