from pydantic import BaseModel


class RankingEntry(BaseModel):
    rank: int
    user_id: int
    nickname: str
    college: str
    department: str
    manner_score: float
    tier: str
    tier_rank: int
    primary_position: str
    riot_id: str | None = None


class RankingListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RankingEntry]


class MyRankingResponse(BaseModel):
    user_id: int
    rank: int | None
    total_players: int | None = None
    tier: str | None = None
    tier_rank: int | None = None
    percentile: float | None = None
    message: str | None = None
    has_lol_profile: bool = True
