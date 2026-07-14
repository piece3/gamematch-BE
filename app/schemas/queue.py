from datetime import datetime
from pydantic import BaseModel, ConfigDict


class QueueJoinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game: str
    tier: str
    tier_rank: int
    position: str
    play_styles: list[str] | None
    status: str
    joined_at: datetime


class QueueStatusResponse(BaseModel):
    in_queue: bool
    match_id: int | None = None
    match_status: str | None = None
    status: str | None = None
    game: str | None = None
    tier: str | None = None
    tier_rank: int | None = None
    position: str | None = None
    elapsed_seconds: int = 0
    allowed_tier_delta: int = 0
    waiting_count: int = 0
    message: str | None = None
