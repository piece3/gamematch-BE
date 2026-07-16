from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_verified_user
from app.database import get_db
from app.models.lol_profile import LolProfile
from app.models.queue_entry import QueueEntry
from app.models.user import User
from app.schemas.lolprofile import (
    GameSettingsUpdate,
    LolProfileResponse,
    ProfileMeResponse,
    ProfileMeUpdate,
    RiotSyncRequest,
)
from app.services.ranking import tier_to_ranking_score
from app.services.matchmaking import tier_to_rank
from app.services.riot import RiotApiError, fetch_rank_by_riot_id

router = APIRouter(prefix="/profile", tags=["profile"])


def _get_or_create_lol_profile(db: Session, user_id: int) -> LolProfile:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user_id))
    if profile is None:
        profile = LolProfile(
            user_id=user_id,
            tier="UN_RANKED",
            tier_rank=0,
            primary_position="ANYTHING",
            secondary_position="ANYTHING",
            play_styles=[],
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _to_profile_response(user: User, lol_profile: LolProfile | None) -> ProfileMeResponse:
    return ProfileMeResponse(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        discord_id=user.discord_id,
        college=user.college,
        department=user.department,
        voice_chat_enable=user.voice_chat_enable,
        manner_score=user.manner_score,
        lol_profile=LolProfileResponse.model_validate(lol_profile) if lol_profile else None,
    )


def _update_waiting_queue_tier(db: Session, profile: LolProfile) -> None:
    entry = db.scalar(
        select(QueueEntry)
        .where(
            QueueEntry.user_id == profile.user_id,
            QueueEntry.status == "waiting",
        )
        .with_for_update()
    )
    if entry is not None:
        entry.tier = profile.tier
        entry.tier_rank = tier_to_rank(profile.tier)


def _apply_riot_rank(
    db: Session,
    profile: LolProfile,
    riot_id: str,
) -> None:
    result = fetch_rank_by_riot_id(riot_id)
    owner = db.scalar(
        select(LolProfile).where(
            LolProfile.puuid == result.puuid,
            LolProfile.id != profile.id,
        )
    )
    if owner is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이 Riot 계정은 이미 다른 사용자에게 연결되어 있습니다.",
        )
    profile.riot_id = result.riot_id
    profile.puuid = result.puuid
    profile.tier = result.tier
    profile.tier_rank = tier_to_ranking_score(result.tier)
    profile.rank_division = result.rank_division
    profile.league_points = result.league_points
    profile.tier_updated_at = datetime.now(UTC)
    _update_waiting_queue_tier(db, profile)


def _refresh_allowed(profile: LolProfile) -> None:
    if profile.tier_updated_at is None:
        return
    updated = profile.tier_updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    hours = settings.riot_tier_refresh_hours
    if datetime.now(UTC) - updated < timedelta(hours=hours):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"티어는 {hours}시간에 한 번만 갱신할 수 있습니다."
            ),
        )


def _raise_riot_http_error(exc: RiotApiError) -> None:
    code = status.HTTP_502_BAD_GATEWAY
    detail = str(exc)
    if exc.status_code == 400:
        code = status.HTTP_400_BAD_REQUEST
    elif exc.status_code == 404:
        code = status.HTTP_404_NOT_FOUND
        detail = "입력한 Riot ID 계정을 찾을 수 없습니다."
    elif exc.status_code == 429:
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif exc.status_code == 503:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    if "Third Party Code" in detail:
        detail = "Riot 계정 확인 방식이 변경되었습니다. Riot ID를 다시 확인해 주세요."
    headers = None
    if exc.retry_after is not None:
        headers = {"Retry-After": str(exc.retry_after)}
    raise HTTPException(
        status_code=code,
        detail=detail,
        headers=headers,
    ) from exc


def _commit_riot_profile(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이 Riot 계정은 이미 다른 사용자에게 연결되어 있습니다.",
        ) from exc


@router.get("/me", response_model=ProfileMeResponse)
def get_profile_me(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileMeResponse:
    lol_profile = db.scalar(select(LolProfile).where(LolProfile.user_id == current_user.id))
    return _to_profile_response(current_user, lol_profile)


@router.patch("/me", response_model=ProfileMeResponse)
def update_profile_me(
    payload: ProfileMeUpdate,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileMeResponse:
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(current_user, key, value)

    db.commit()
    db.refresh(current_user)

    lol_profile = db.scalar(select(LolProfile).where(LolProfile.user_id == current_user.id))
    return _to_profile_response(current_user, lol_profile)


@router.patch("/game-settings", response_model=ProfileMeResponse)
def update_game_settings(
    payload: GameSettingsUpdate,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileMeResponse:
    profile = _get_or_create_lol_profile(db, current_user.id)

    profile.primary_position = payload.primary_position.value
    profile.secondary_position = payload.secondary_position.value
    profile.play_styles = payload.play_styles

    requested_riot_id = (
        payload.riot_id.strip()
        if payload.riot_id is not None
        else profile.riot_id
    )

    if payload.sync_tier_from_riot:
        if not requested_riot_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Riot 티어 동기화에는 riot_id가 필요합니다. (예: 닉네임#KR1)",
            )
        _refresh_allowed(profile)
        try:
            _apply_riot_rank(db, profile, requested_riot_id)
        except RiotApiError as exc:
            _raise_riot_http_error(exc)
    elif payload.riot_id is not None and requested_riot_id != profile.riot_id:
        profile.riot_id = requested_riot_id or None
        profile.puuid = None
        profile.tier = "UN_RANKED"
        profile.tier_rank = 0
        profile.rank_division = None
        profile.league_points = None
        profile.tier_updated_at = None
        _update_waiting_queue_tier(db, profile)

    _commit_riot_profile(db)
    db.refresh(profile)
    db.refresh(current_user)

    return _to_profile_response(current_user, profile)


@router.post("/riot/sync", response_model=ProfileMeResponse)
def sync_riot_profile(
    payload: RiotSyncRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileMeResponse:
    """Riot ID 저장 + 솔랭 티어 즉시 동기화."""
    profile = _get_or_create_lol_profile(db, current_user.id)
    _refresh_allowed(profile)
    try:
        _apply_riot_rank(db, profile, payload.riot_id)
    except RiotApiError as exc:
        _raise_riot_http_error(exc)

    _commit_riot_profile(db)
    db.refresh(profile)
    db.refresh(current_user)
    return _to_profile_response(current_user, profile)


@router.post("/riot/refresh", response_model=ProfileMeResponse)
def refresh_riot_tier(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileMeResponse:
    """저장된 riot_id로 티어 재조회 (기본 72시간에 1회)."""
    profile = _get_or_create_lol_profile(db, current_user.id)
    if not profile.riot_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="먼저 POST /profile/riot/sync 로 Riot ID를 등록하세요.",
        )

    _refresh_allowed(profile)

    try:
        _apply_riot_rank(db, profile, profile.riot_id)
    except RiotApiError as exc:
        _raise_riot_http_error(exc)

    _commit_riot_profile(db)
    db.refresh(profile)
    db.refresh(current_user)
    return _to_profile_response(current_user, profile)
