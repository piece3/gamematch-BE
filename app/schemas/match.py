from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MatchMemberSummary(BaseModel):
    user_id: int
    nickname: str
    college: str
    department: str
    manner_score: float
    voice_chat_enable: bool
    tier: str
    position: str
    assigned_role: str
    play_styles: list[str] | None
    accept_status: str


class MatchDetailResponse(BaseModel):
    id: int
    game: str
    game_mode: str | None = None
    status: str
    accept_deadline: datetime | None
    created_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None = None
    evaluation_deadline: datetime | None = None
    my_accept_status: str | None = None
    riot_match_id: str | None = None
    result_status: str | None = None


class MatchMembersResponse(BaseModel):
    match_id: int
    status: str
    members: list[MatchMemberSummary]


class AcceptStatusResponse(BaseModel):
    match_id: int
    status: str
    accept_deadline: datetime | None
    accepted_count: int
    pending_count: int
    declined_count: int
    seconds_remaining: int
    all_accepted: bool


class MatchActionResponse(BaseModel):
    match_id: int
    status: str
    my_accept_status: str
    message: str


class EvaluationItem(BaseModel):
    target_user_id: int
    manner_delta: int = Field(description="-1, 0, 1")

    @field_validator("manner_delta")
    @classmethod
    def validate_delta(cls, v: int) -> int:
        if v not in (-1, 0, 1):
            raise ValueError("manner_delta는 -1, 0, 1 만 가능합니다.")
        return v


class MatchEvaluateRequest(BaseModel):
    evaluations: list[EvaluationItem]


class MatchEvaluateResponse(BaseModel):
    match_id: int
    submitted_count: int
    message: str


class EvaluationStatusResponse(BaseModel):
    match_id: int
    required_count: int
    submitted_count: int
    is_complete: bool
    evaluation_deadline: datetime | None = None
    seconds_remaining: int = 0


class MatchHistoryItem(BaseModel):
    match_id: int
    game: str
    game_mode: str | None = None
    status: str
    my_assigned_role: str
    my_tier: str
    member_count: int
    confirmed_at: datetime | None
    completed_at: datetime | None
    evaluation_submitted: bool
    won: bool | None = None
    result_status: str | None = None


class MatchHistoryResponse(BaseModel):
    total: int
    items: list[MatchHistoryItem]


class PersonalRecordItem(BaseModel):
    match_id: int
    riot_match_id: str
    game_mode: str
    won: bool
    played_at: datetime


class PersonalRecordsResponse(BaseModel):
    total: int
    limit: int = 5
    items: list[PersonalRecordItem]
