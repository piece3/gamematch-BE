from sqlalchemy import case, func, select
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
    division_score = case(
        (LolProfile.rank_division == "I", 4),
        (LolProfile.rank_division == "II", 3),
        (LolProfile.rank_division == "III", 2),
        (LolProfile.rank_division == "IV", 1),
        else_=0,
    )
    ordering = (
        LolProfile.tier_rank.desc(),
        division_score.desc(),
        LolProfile.league_points.desc().nullslast(),
        User.manner_score.desc(),
        User.id.asc(),
    )
    q = (
        select(
            func.row_number().over(order_by=ordering).label("rank"),
            User.id.label("user_id"),
            User.nickname,
            User.manner_score,
            LolProfile.tier,
            LolProfile.tier_rank,
            LolProfile.rank_division,
            LolProfile.league_points,
            LolProfile.primary_position,
            LolProfile.riot_id,
        )
        .join(LolProfile, LolProfile.user_id == User.id)
        .where(
            User.is_verified.is_(True),
            LolProfile.puuid.is_not(None),
        )
    )
    if not include_unranked:
        q = q.where(LolProfile.tier != "UN_RANKED")
    return q


def list_lol_ranking(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    include_unranked: bool = False,
) -> tuple[list, int]:
    ranked = _ranked_users_query(include_unranked).subquery()
    total = db.scalar(select(func.count()).select_from(ranked)) or 0
    rows = db.execute(
        select(ranked)
        .order_by(ranked.c.rank)
        .offset(offset)
        .limit(limit)
    ).all()
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
            "rank_division": profile.rank_division,
            "league_points": profile.league_points,
            "riot_id": profile.riot_id,
            "total_players": None,
            "percentile": None,
            "message": "UN_RANKED는 랭킹 보드에 포함되지 않습니다.",
        }

    ranked = _ranked_users_query(include_unranked).subquery()
    row = db.execute(
        select(ranked).where(ranked.c.user_id == user_id)
    ).one_or_none()
    if row is None:
        return None
    total = db.scalar(select(func.count()).select_from(ranked)) or 0
    my_rank = row.rank

    return {
        "user_id": user_id,
        "rank": my_rank,
        "total_players": total,
        "tier": profile.tier,
        "tier_rank": profile.tier_rank,
        "rank_division": profile.rank_division,
        "league_points": profile.league_points,
        "riot_id": profile.riot_id,
        "percentile": round((1 - (my_rank - 1) / total) * 100, 1) if total else None,
        "message": None,
    }
