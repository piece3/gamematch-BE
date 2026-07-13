from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class QueueEntry(Base):
    __tablename__ = "queue_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id",ondelete="Cascade"),
        unique=True,
        index=True,
        nullable=False,
        )
    game: Mapped[str] = mapped_column(String(20),default="lol",nullable=False)
    tier: Mapped[str] = mapped_column(String(20),nullable=False)
    tier_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[str] = mapped_column(String(20),nullable=False)
    play_styles: Mapped[list | None] = mapped_column(JSONB,nullable=True)
    status: Mapped[str] = mapped_column(String(20),default="waiting",nullable=False)
    joined_at:Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        )