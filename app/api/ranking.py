from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.lol_profile import LolProfile
from app.models.user import User
from app.schemas.ranking import MyRankingResponse, RankingEntry, RankingListResponse
from app.services.ranking import get_user_rank, list_lol_ranking

router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("/lol", response_model=RankingListResponse)
def get_lol_ranking(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_unranked: Annotated[bool, Query()] = False,
) -> RankingListResponse:
    rows, total = list_lol_ranking(
        db, limit=limit, offset=offset, include_unranked=include_unranked
    )
    items = [
        RankingEntry(
            rank=offset + i,
            user_id=row.user_id,
            nickname=row.nickname,
            college=row.college,
            department=row.department,
            manner_score=row.manner_score,
            tier=row.tier,
            tier_rank=row.tier_rank,
            primary_position=row.primary_position,
            riot_id=row.riot_id,
        )
        for i, row in enumerate(rows, start=1)
    ]
    return RankingListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/me", response_model=MyRankingResponse)
def get_my_ranking(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_unranked: Annotated[bool, Query()] = False,
) -> MyRankingResponse:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == current_user.id))
    if profile is None:
        return MyRankingResponse(
            user_id=current_user.id,
            rank=None,
            has_lol_profile=False,
            message="롤 프로필이 없습니다. /profile/game-settings 를 설정하세요.",
        )

    info = get_user_rank(db, current_user.id, include_unranked=include_unranked)
    if info is None:
        return MyRankingResponse(
            user_id=current_user.id,
            rank=None,
            tier=profile.tier,
            tier_rank=profile.tier_rank,
            has_lol_profile=True,
            message="순위를 계산할 수 없습니다.",
        )

    return MyRankingResponse(
        user_id=info["user_id"],
        rank=info.get("rank"),
        total_players=info.get("total_players"),
        tier=info.get("tier"),
        tier_rank=info.get("tier_rank"),
        percentile=info.get("percentile"),
        message=info.get("message"),
        has_lol_profile=True,
    )
