from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.lol_profile import LolProfile
from app.models.user import User

# 랭킹 전용 (매칭 TIER_RANK UN_RANKED=3 과 분리)
RANKING_TIER_SCORE: dict[str, int] = {
    "UN_RANKED": 0,
    "IRON": 1,
    "BRONZE": 2,
    "SILVER": 3,
    "GOLD": 4,
    "PLATINUM": 5,
    "EMERALD": 6,
    "DIAMOND": 7,
    "MASTER": 8,
    "GRANDMASTER": 9,
    "CHALLENGER": 10,
}


def tier_to_ranking_score(tier: str) -> int:
    return RANKING_TIER_SCORE.get(tier, 0)


def _ranked_users_query(include_unranked: bool = False):
    q = (
        select(
            User.id.label("user_id"),
            User.nickname,
            User.college,
            User.department,
            User.manner_score,
            LolProfile.tier,
            LolProfile.tier_rank,
            LolProfile.primary_position,
            LolProfile.riot_id,
        )
        .join(LolProfile, LolProfile.user_id == User.id)
        .where(User.is_verified.is_(True))
    )
    if not include_unranked:
        q = q.where(LolProfile.tier != "UN_RANKED")
    return q.order_by(
        LolProfile.tier_rank.desc(),
        User.manner_score.desc(),
        User.id.asc(),
    )


def list_lol_ranking(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    include_unranked: bool = False,
) -> tuple[list, int]:
    base = _ranked_users_query(include_unranked)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.offset(offset).limit(limit)).all()
    return rows, total


def get_user_rank(
    db: Session,
    user_id: int,
    *,
    include_unranked: bool = False,
) -> dict | None:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user_id))
    if profile is None:
        return None
    if not include_unranked and profile.tier == "UN_RANKED":
        return {
            "user_id": user_id,
            "rank": None,
            "tier": profile.tier,
            "tier_rank": profile.tier_rank,
            "total_players": None,
            "percentile": None,
            "message": "UN_RANKED는 랭킹 보드에 포함되지 않습니다.",
        }

    rows, total = list_lol_ranking(
        db, limit=10_000, offset=0, include_unranked=include_unranked
    )
    my_rank = None
    for i, row in enumerate(rows, start=1):
        if row.user_id == user_id:
            my_rank = i
            break

    if my_rank is None:
        return None

    return {
        "user_id": user_id,
        "rank": my_rank,
        "total_players": total,
        "tier": profile.tier,
        "tier_rank": profile.tier_rank,
        "percentile": round((1 - (my_rank - 1) / total) * 100, 1) if total else None,
        "message": None,
    }
