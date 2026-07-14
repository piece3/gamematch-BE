from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    status: str
    accept_deadline: datetime | None
    created_at: datetime
    confirmed_at: datetime | None
    my_accept_status: str | None = None


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