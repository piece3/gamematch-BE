from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.lol_profile import LolProfile
from app.models.queue_entry import QueueEntry
from app.models.user import User
from app.schemas.queue import QueueJoinResponse, QueueStatusResponse
from app.services.matchmaking import (
    allowed_tier_delta,
    calc_elapsed_seconds,
    tier_to_rank,
)


router = APIRouter(prefix="/match",tags=["match"])

def _get_lol_profile_or_400(db:Session, user_id: int) -> LolProfile:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user_id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="롤 프로필이 없습니다. 먼저 롤 프로필을 설정하세요",
    )
    return profile

@router.post("/queue/join",response_model=QueueJoinResponse, status_code=status.HTTP_201_CREATED)
def join_queue(
    current_user: Annotated[User,Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    ) -> QueueEntry:
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증 후 매칭을 이용할 수 있습니다",
            )

    existing = db.scalar(select(QueueEntry).where(QueueEntry.user_id == current_user.id))
    if existing is not None:
        raise HTTPException(
            status_code = status.HTTP_409_CONFLICT,
            detail="이미 매칭 대기 중",
            )

    lol_profile = _get_lol_profile_or_400(db,current_user.id)

    entry = QueueEntry(
        user_id=current_user.id,
        game="lol",
        tier=lol_profile.tier,
        tier_rank = tier_to_rank(lol_profile.tier),
        position=lol_profile.primary_position,
        play_styles=lol_profile.play_styles or [],
        status="waiting",)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry



@router.get("/queue/status",response_model=QueueStatusResponse)
def queue_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    ) -> QueueStatusResponse:
    entry = db.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id ==current_user.id,
            QueueEntry.status == "waiting",
            )
        )
    if entry is None:
        return QueueStatusResponse(in_queue=False, message= "매칭 대기 중이 아닙니다")

    elapsed = calc_elapsed_seconds(entry.joined_at)
    delta = allowed_tier_delta(elapsed)

    waiting_count = db.scalar(
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.status == "waiting", QueueEntry.game == "lol")
        ) or 0

    return QueueStatusResponse(
        in_queue=True,
        status=entry.status,
        game=entry.game,
        tier=entry.tier,
        tier_rank=entry.tier_rank,
        position=entry.position,
        elapsed_seconds=elapsed,
        allowed_tier_delta=delta,
        waiting_count=waiting_count,
        message="매칭 대기 중입니다.",
    )

@router.delete("/queue/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_queue(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    entry = db.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == current_user.id,
            QueueEntry.status == "waiting",
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="매칭 대기 중이 아닙니다.",
        )

    db.delete(entry)
    db.commit()