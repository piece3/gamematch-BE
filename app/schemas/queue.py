from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class GameMode(str, Enum):
    """Matching queue / Riot queue family."""

    SOLO = "SOLO"  # 솔랭
    FLEX = "FLEX"  # 자랭
    NORMAL = "NORMAL"  # 증바람(블라인드)


GAME_MODE_LABELS = {
    GameMode.SOLO: "솔랭",
    GameMode.FLEX: "자랭",
    GameMode.NORMAL: "증바람",
}

# Riot match-v5 queueId
GAME_MODE_QUEUE_IDS = {
    GameMode.SOLO: (420,),
    GameMode.FLEX: (440,),
    GameMode.NORMAL: (430,),  # Blind Pick / 증바람
}


class QueueJoinRequest(BaseModel):
    game_mode: GameMode = GameMode.SOLO


class QueueJoinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game: str
    game_mode: str
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
    game_mode: str | None = None
    tier: str | None = None
    tier_rank: int | None = None
    position: str | None = None
    elapsed_seconds: int = 0
    allowed_tier_delta: int = 0
    waiting_count: int = 0
    message: str | None = None
