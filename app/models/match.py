from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_accept', 'confirmed', 'cancelled', 'completed')",
            name="ck_matches_status",
        ),
        CheckConstraint(
            "(game = 'lol' AND game_mode IN ('SOLO', 'FLEX', 'Howling Abyss')) "
            "OR (game = 'fc_online' AND game_mode IN ('OFFICIAL_1V1', 'OFFICIAL_2V2'))",
            name="ck_matches_game_mode",
        ),
        CheckConstraint(
            "(game = 'lol' AND party_size = 1) "
            "OR (game_mode = 'OFFICIAL_1V1' AND party_size = 1) "
            "OR (game_mode = 'OFFICIAL_2V2' AND party_size = 2)",
            name="ck_matches_party_size",
        ),
        CheckConstraint(
            "result_status IN ('pending', 'synced', 'unresolved')",
            name="ck_matches_result_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game: Mapped[str] = mapped_column(String(20), default="lol", nullable=False)
    game_mode: Mapped[str] = mapped_column(
        String(20), default="SOLO", nullable=False
    )
    party_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    riot_match_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nexon_match_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    accept_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    evaluation_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MatchMember(Base):
    __tablename__ = "match_members"
    __table_args__ = (
        UniqueConstraint("match_id", "user_id", name="uq_match_members_match_user"),
        UniqueConstraint("match_id", "assigned_role", name="uq_match_members_match_role"),
        CheckConstraint(
            "accept_status IN ('pending', 'accepted', 'declined')",
            name="ck_match_members_accept_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(String(50), nullable=False)
    tier_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[str] = mapped_column(String(20), nullable=False)
    play_styles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    assigned_role: Mapped[str] = mapped_column(String(20), nullable=False)
    accept_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
