from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FcOnlineProfile(Base):
    __tablename__ = "fc_online_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    ouid: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    division_1v1_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    division_1v1_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    division_1v1_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    division_2v2_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    division_2v2_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    division_2v2_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
