from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

class LoLTier(str,Enum):
    UN_RANK="UN_RANKED"
    IRON = "IRON"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"
    EMERALD = "EMERALD"
    DIAMOND = "DIAMOND"
    MASTER = "MASTER"
    GRANDMASTER = "GRANDMASTER"
    CHALLENGER = "CHALLENGER"


class LoLPosition(str,Enum):
    TOP = "TOP"
    JUNGLE = "JUNGLE"
    MID = "MID"
    ADC = "ADC"
    SUPPORT = "SUPPORT"
    ANYTHING = "상관없음"


ALLOWED_PLAY_STYLES = {
    "즐겜",
    "승리우선",
    "친목",
    "초보환영",
    }

class ProfileMeUpdate(BaseModel):
    """PATCH /profile/me"""

    discord_id: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=50)
    voice_chat_enable: bool | None = None


class GameSettingsUpdate(BaseModel):
    """PATCH /profile/game-settings """

    tier: LoLTier
    primary_position: LoLPosition
    secondary_position: LoLPosition
    play_styles: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("play_styles")
    @classmethod
    def validate_play_styles(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in ALLOWED_PLAY_STYLES]
        if invalid:
            raise ValueError(f"허용되지 않는 성향 태그: {invalid}")
        return v


class LolProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: str
    primary_position: str
    secondary_position: str
    play_styles: list[str] | None
    updated_at: datetime | None = None


class ProfileMeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str
    discord_id: str | None
    department: str
    voice_chat_enable: bool
    manner_score: float
    lol_profile: LolProfileResponse | None