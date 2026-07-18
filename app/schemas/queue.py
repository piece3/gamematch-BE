from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GameMode(str, Enum):
    """Matching queue / Riot queue family."""

    SOLO = "SOLO"  # 솔랭
    FLEX = "FLEX"  # 자랭
    HOWLING_ABYSS = "Howling Abyss"  # 칼바람


class FcGameMode(str, Enum):
    OFFICIAL_1V1 = "OFFICIAL_1V1"
    OFFICIAL_2V2 = "OFFICIAL_2V2"


class GameName(str, Enum):
    LOL = "lol"
    FC_ONLINE = "fc_online"


GAME_MODE_LABELS = {
    GameMode.SOLO: "솔랭",
    GameMode.FLEX: "자랭",
    GameMode.HOWLING_ABYSS: "칼바람",
}

# Riot match-v5 queueId
GAME_MODE_QUEUE_IDS = {
    GameMode.SOLO: (420,),
    GameMode.FLEX: (440,),
    GameMode.HOWLING_ABYSS: (450,),  # ARAM / Howling Abyss
}


class QueueJoinRequest(BaseModel):
    game: GameName = GameName.LOL
    game_mode: str = GameMode.SOLO.value
    party_size: int = Field(default=1, ge=1, le=2)

    @model_validator(mode="after")
    def validate_game_mode(self) -> "QueueJoinRequest":
        if self.game == GameName.LOL:
            allowed = {mode.value for mode in GameMode}
            if self.game_mode not in allowed:
                raise ValueError(f"LoL game_mode는 {sorted(allowed)} 중 하나여야 합니다.")
            if self.party_size != 1:
                raise ValueError("현재 LoL 매칭은 1인 큐만 지원합니다.")
            return self

        expected_size = {
            FcGameMode.OFFICIAL_1V1.value: 1,
            FcGameMode.OFFICIAL_2V2.value: 2,
        }.get(self.game_mode)
        if expected_size is None:
            raise ValueError("FC 온라인 game_mode는 OFFICIAL_1V1 또는 OFFICIAL_2V2여야 합니다.")
        if self.party_size != expected_size:
            raise ValueError(
                f"{self.game_mode}의 party_size는 {expected_size}이어야 합니다."
            )
        return self


class QueueJoinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game: str
    game_mode: str
    party_size: int
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
    party_size: int | None = None
    tier: str | None = None
    tier_rank: int | None = None
    position: str | None = None
    elapsed_seconds: int = 0
    allowed_tier_delta: int = 0
    waiting_count: int = 0
    message: str | None = None
