from datetime import UTC,datetime

TIER_RANK: dict[str,int] = {
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

def tier_to_rank(tier:str) -> int:
    try:
        return TIER_RANK[tier]
    except KeyError as exc:
        raise ValueError(f"Unknown tier: {tier}") from exc



def allowed_tier_delta(elapsed_seconds:int)->int:
    if elapsed_seconds < 30:
        return 0
    if elapsed_seconds < 60:
        return 1
    if elapsed_seconds < 90:
        return 3
    return 4

def is_tier_compatible(my_rank: int, other_rank:int, elapsed_seconds: int)->bool:
    delta = allowed_tier_delta(elapsed_seconds)
    return abs(my_rank - other_rank) <= delta

def calc_elapsed_seconds(joined_at:datetime) -> int:
    now = datetime.now(UTC)
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=UTC)
        return max (0,int((now-joined_at).total_seconds()))
