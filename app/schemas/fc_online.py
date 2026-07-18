from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FcOnlineSyncRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=50)

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("nickname must not be blank")
        return normalized


class FcOnlineProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    nickname: str
    ouid: str
    level: int | None
    division_1v1_id: int | None
    division_1v1_name: str | None
    division_1v1_rank: int | None
    division_2v2_id: int | None
    division_2v2_name: str | None
    division_2v2_rank: int | None
    synced_at: datetime
    created_at: datetime
    updated_at: datetime


class FcOnlineMatchRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    nexon_match_id: str
    game_mode: str
    result: Literal["WIN", "DRAW", "LOSS"]
    played_at: datetime
    created_at: datetime


class FcOnlineRecordsResponse(BaseModel):
    total: int
    limit: int = 5
    items: list[FcOnlineMatchRecordResponse]
