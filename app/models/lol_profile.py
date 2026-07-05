from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class LolProfile(Base):
    __tablename__= "lol_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id",ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
        )
    tier: Mapped[str] = mapped_column(String(20),nullable=False)
    primary_position: Mapped[str] = mapped_column(String(10), nullable=False)
    secondary_position: Mapped[str] = mapped_column(String(10), nullable=False)
    play_styles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )