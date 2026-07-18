from datetime import UTC, datetime, timedelta
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_verified_user
from app.database import get_db
from app.models.fc_online_match_record import (
    MAX_FC_ONLINE_RECORDS_PER_USER,
    FcOnlineMatchRecord,
)
from app.models.fc_online_profile import FcOnlineProfile
from app.models.user import User
from app.schemas.fc_online import (
    FcOnlineMatchRecordResponse,
    FcOnlineProfileResponse,
    FcOnlineRecordsResponse,
    FcOnlineSyncRequest,
)
from app.services.fc_online import (
    FcOnlineApiError,
    FcOnlineSyncPayload,
    fetch_ouid,
    fetch_sync_payload_for_ouid,
)

router = APIRouter(prefix="/profile/fc-online", tags=["fc-online"])


def _get_profile(db: Session, user_id: int) -> FcOnlineProfile | None:
    return db.scalar(
        select(FcOnlineProfile).where(FcOnlineProfile.user_id == user_id)
    )


def _refresh_allowed(profile: FcOnlineProfile) -> None:
    synced_at = profile.synced_at
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=UTC)
    minutes = int(getattr(settings, "fc_online_refresh_minutes", 10))
    if datetime.now(UTC) - synced_at < timedelta(minutes=minutes):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"FC Online profile can be refreshed once every {minutes} minutes.",
        )


def _raise_api_error(exc: FcOnlineApiError) -> NoReturn:
    response_status = status.HTTP_502_BAD_GATEWAY
    if exc.status_code == 404:
        response_status = status.HTTP_404_NOT_FOUND
    elif exc.status_code == 429:
        response_status = status.HTTP_429_TOO_MANY_REQUESTS
    elif exc.status_code in (401, 403, 503):
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif exc.status_code == 504:
        response_status = status.HTTP_504_GATEWAY_TIMEOUT
    headers = (
        {"Retry-After": str(exc.retry_after)}
        if exc.retry_after is not None
        else None
    )
    raise HTTPException(
        status_code=response_status,
        detail=str(exc),
        headers=headers,
    ) from exc


def _ensure_ouid_available(
    db: Session,
    *,
    ouid: str,
    profile_id: int | None,
) -> None:
    statement = select(FcOnlineProfile).where(FcOnlineProfile.ouid == ouid)
    if profile_id is not None:
        statement = statement.where(FcOnlineProfile.id != profile_id)
    if db.scalar(statement) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This FC Online account is already linked to another user.",
        )


def _apply_sync_payload(
    profile: FcOnlineProfile,
    payload: FcOnlineSyncPayload,
) -> None:
    profile.nickname = payload.nickname
    profile.ouid = payload.ouid
    profile.level = payload.level
    profile.division_1v1_id = payload.division_1v1.division_id
    profile.division_1v1_name = payload.division_1v1.division_name
    profile.division_1v1_rank = payload.division_1v1.division_rank
    profile.division_2v2_id = payload.division_2v2.division_id
    profile.division_2v2_name = payload.division_2v2.division_name
    profile.division_2v2_rank = payload.division_2v2.division_rank
    profile.synced_at = datetime.now(UTC)


def _commit_profile(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This FC Online account is already linked to another user.",
        ) from exc


def _fetch_for_ouid(ouid: str) -> FcOnlineSyncPayload:
    try:
        return fetch_sync_payload_for_ouid(ouid)
    except FcOnlineApiError as exc:
        _raise_api_error(exc)


@router.post("/sync", response_model=FcOnlineProfileResponse)
def sync_fc_online_profile(
    payload: FcOnlineSyncRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FcOnlineProfile:
    profile = _get_profile(db, current_user.id)
    try:
        ouid = fetch_ouid(payload.nickname)
    except FcOnlineApiError as exc:
        _raise_api_error(exc)

    # Re-syncing the same account is a refresh; linking a different account is not.
    if profile is not None and profile.ouid == ouid:
        _refresh_allowed(profile)
    _ensure_ouid_available(
        db,
        ouid=ouid,
        profile_id=profile.id if profile is not None else None,
    )

    api_payload = _fetch_for_ouid(ouid)
    if profile is None:
        profile = FcOnlineProfile(
            user_id=current_user.id,
            nickname=api_payload.nickname,
            ouid=api_payload.ouid,
            synced_at=datetime.now(UTC),
        )
        db.add(profile)
    _apply_sync_payload(profile, api_payload)
    _commit_profile(db)
    db.refresh(profile)
    return profile


@router.post("/refresh", response_model=FcOnlineProfileResponse)
def refresh_fc_online_profile(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FcOnlineProfile:
    profile = _get_profile(db, current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link an FC Online account before refreshing.",
        )
    _refresh_allowed(profile)
    api_payload = _fetch_for_ouid(profile.ouid)
    _ensure_ouid_available(db, ouid=api_payload.ouid, profile_id=profile.id)
    _apply_sync_payload(profile, api_payload)
    _commit_profile(db)
    db.refresh(profile)
    return profile


@router.get("", response_model=FcOnlineProfileResponse)
def get_fc_online_profile(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FcOnlineProfile:
    profile = _get_profile(db, current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FC Online profile is not linked.",
        )
    return profile


@router.get("/records", response_model=FcOnlineRecordsResponse)
def get_fc_online_records(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FcOnlineRecordsResponse:
    records = list(
        db.scalars(
            select(FcOnlineMatchRecord)
            .where(FcOnlineMatchRecord.user_id == current_user.id)
            .order_by(
                FcOnlineMatchRecord.played_at.desc(),
                FcOnlineMatchRecord.id.desc(),
            )
            .limit(MAX_FC_ONLINE_RECORDS_PER_USER)
        )
    )
    return FcOnlineRecordsResponse(
        total=len(records),
        limit=MAX_FC_ONLINE_RECORDS_PER_USER,
        items=[
            FcOnlineMatchRecordResponse.model_validate(record)
            for record in records
        ],
    )
