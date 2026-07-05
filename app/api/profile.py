from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.lol_profile import LolProfile
from app.models.user import User
from app.schemas.lolprofile import (
    GameSettingsUpdate,
    LolProfileResponse,
    ProfileMeResponse,
    ProfileMeUpdate,
)

router = APIRouter(prefix="/profile", tags = ["profile"])

def _get_or_greate_lol_profile(db: Session, user_id: int) -> LolProfile:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user_id))
    if profile is None:
        profile = LolProfile(
            user_id = user_id,
            tier="UN_RANKED",
            primary_position="ANYTHING",
            secondary_position ="ANYTHING",
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

@router.get("/me", response_model=ProfileMeResponse)
def get_profile_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    ) -> ProfileMeResponse:
    lol_profile = db.scalar(select(LolProfile).where(LolProfile.user_id == current_user.id))
    return _to_profile_response(current_user, lol_profile)

@router.patch("/me", response_model=ProfileMeResponse)
def update_profile_me(
    payload: ProfileMeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session,Depends(get_db)],
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
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    ) -> ProfileMeResponse:
    profile = _get_or_greate_lol_profile(db,current_user.id)

    profile.tier = payload.tier.value
    profile.primary_position = payload.primary_position.value
    profile.secondary_position = payload.secondary_position.value
    profile.play_styles = payload.play_styles

    db.commit()
    db.refresh(profile)
    db.refresh(current_user)

    return _to_profile_response(current_user, profile)