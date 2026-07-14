from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.lol_profile import LolProfile
from app.models.match import Match, MatchMember
from app.models.queue_entry import QueueEntry
from app.models.user import User
from app.schemas.match import (
    AcceptStatusResponse,
    MatchActionResponse,
    MatchDetailResponse,
    MatchMemberSummary,
    MatchMembersResponse,
)
from app.schemas.queue import QueueJoinResponse, QueueStatusResponse
from app.services.matchmaking import (
    allowed_tier_delta,
    calc_elapsed_seconds,
    cancel_match_and_requeue,
    tier_to_rank,
    try_form_match,
)

router = APIRouter(prefix="/match", tags=["match"])


def _get_lol_profile_or_400(db: Session, user_id: int) -> LolProfile:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user_id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="롤 프로필이 없습니다. 먼저 /profile/game-settings 를 설정하세요.",
        )
    return profile


def _get_match_or_404(db: Session, match_id: int) -> Match:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="매칭을 찾을 수 없습니다.",
        )
    return match


def _get_member_or_403(db: Session, match_id: int, user_id: int) -> MatchMember:
    member = db.scalar(
        select(MatchMember).where(
            MatchMember.match_id == match_id,
            MatchMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 매칭의 멤버가 아닙니다.",
        )
    return member


def _expire_if_needed(db: Session, match: Match) -> None:
    if match.status != "pending_accept":
        return
    if match.accept_deadline is None:
        return
    now = datetime.now(UTC)
    deadline = match.accept_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if now > deadline:
        cancel_match_and_requeue(db, match)


def _find_active_match_for_user(db: Session, user_id: int) -> Match | None:
    return db.scalar(
        select(Match)
        .join(MatchMember, MatchMember.match_id == Match.id)
        .where(
            MatchMember.user_id == user_id,
            Match.status.in_(("pending_accept", "confirmed")),
        )
        .order_by(Match.created_at.desc())
    )


@router.post("/queue/join", response_model=QueueJoinResponse, status_code=status.HTTP_201_CREATED)
def join_queue(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QueueEntry:
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증 후 매칭을 이용할 수 있습니다.",
        )

    existing = db.scalar(select(QueueEntry).where(QueueEntry.user_id == current_user.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 매칭 대기 중입니다.",
        )

    lol_profile = _get_lol_profile_or_400(db, current_user.id)

    entry = QueueEntry(
        user_id=current_user.id,
        game="lol",
        tier=lol_profile.tier,
        tier_rank=tier_to_rank(lol_profile.tier),
        position=lol_profile.primary_position,
        play_styles=lol_profile.play_styles or [],
        status="waiting",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    try_form_match(db)
    db.refresh(entry)
    return entry


@router.get("/queue/status", response_model=QueueStatusResponse)
def queue_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QueueStatusResponse:
    try_form_match(db)

    active_match = _find_active_match_for_user(db, current_user.id)
    if active_match is not None:
        _expire_if_needed(db, active_match)
        db.refresh(active_match)
        if active_match.status in ("pending_accept", "confirmed"):
            return QueueStatusResponse(
                in_queue=False,
                match_id=active_match.id,
                match_status=active_match.status,
                message="매칭이 성사되었습니다. 수락/거절을 진행하세요."
                if active_match.status == "pending_accept"
                else "매칭이 확정되었습니다.",
            )

    entry = db.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == current_user.id,
            QueueEntry.status == "waiting",
        )
    )
    if entry is None:
        return QueueStatusResponse(in_queue=False, message="매칭 대기 중이 아닙니다.")

    elapsed = calc_elapsed_seconds(entry.joined_at)
    delta = allowed_tier_delta(elapsed)
    waiting_count = (
        db.scalar(
            select(func.count())
            .select_from(QueueEntry)
            .where(QueueEntry.status == "waiting", QueueEntry.game == "lol")
        )
        or 0
    )

    return QueueStatusResponse(
        in_queue=True,
        status=entry.status,
        game=entry.game,
        tier=entry.tier,
        tier_rank=entry.tier_rank,
        position=entry.position,
        elapsed_seconds=elapsed,
        allowed_tier_delta=delta,
        waiting_count=waiting_count,
        message="매칭 대기 중입니다.",
    )


@router.delete("/queue/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_queue(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    entry = db.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == current_user.id,
            QueueEntry.status == "waiting",
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="매칭 대기 중이 아닙니다.",
        )

    db.delete(entry)
    db.commit()


@router.get("/active", response_model=MatchDetailResponse | None)
def get_active_match(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchDetailResponse | None:
    match = _find_active_match_for_user(db, current_user.id)
    if match is None:
        return None

    _expire_if_needed(db, match)
    db.refresh(match)
    if match.status not in ("pending_accept", "confirmed"):
        return None

    member = _get_member_or_403(db, match.id, current_user.id)
    return MatchDetailResponse(
        id=match.id,
        game=match.game,
        status=match.status,
        accept_deadline=match.accept_deadline,
        created_at=match.created_at,
        confirmed_at=match.confirmed_at,
        my_accept_status=member.accept_status,
    )


@router.get("/{match_id}", response_model=MatchDetailResponse)
def get_match(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchDetailResponse:
    match = _get_match_or_404(db, match_id)
    member = _get_member_or_403(db, match_id, current_user.id)
    _expire_if_needed(db, match)
    db.refresh(match)

    return MatchDetailResponse(
        id=match.id,
        game=match.game,
        status=match.status,
        accept_deadline=match.accept_deadline,
        created_at=match.created_at,
        confirmed_at=match.confirmed_at,
        my_accept_status=member.accept_status,
    )


@router.get("/{match_id}/members", response_model=MatchMembersResponse)
def get_match_members(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchMembersResponse:
    match = _get_match_or_404(db, match_id)
    _get_member_or_403(db, match_id, current_user.id)

    members = db.scalars(
        select(MatchMember).where(MatchMember.match_id == match_id)
    ).all()

    summaries: list[MatchMemberSummary] = []
    for member in members:
        user = db.get(User, member.user_id)
        if user is None:
            continue
        summaries.append(
            MatchMemberSummary(
                user_id=member.user_id,
                nickname=user.nickname,
                college=user.college,
                department=user.department,
                manner_score=user.manner_score,
                voice_chat_enable=user.voice_chat_enable,
                tier=member.tier,
                position=member.position,
                assigned_role=member.assigned_role,
                play_styles=member.play_styles,
                accept_status=member.accept_status,
            )
        )

    return MatchMembersResponse(
        match_id=match.id,
        status=match.status,
        members=summaries,
    )


@router.get("/{match_id}/accept-status", response_model=AcceptStatusResponse)
def accept_status(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AcceptStatusResponse:
    match = _get_match_or_404(db, match_id)
    _get_member_or_403(db, match_id, current_user.id)
    _expire_if_needed(db, match)
    db.refresh(match)

    members = db.scalars(
        select(MatchMember).where(MatchMember.match_id == match_id)
    ).all()

    accepted = sum(1 for m in members if m.accept_status == "accepted")
    pending = sum(1 for m in members if m.accept_status == "pending")
    declined = sum(1 for m in members if m.accept_status == "declined")

    seconds_remaining = 0
    if match.accept_deadline is not None and match.status == "pending_accept":
        deadline = match.accept_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        seconds_remaining = max(0, int((deadline - datetime.now(UTC)).total_seconds()))

    return AcceptStatusResponse(
        match_id=match.id,
        status=match.status,
        accept_deadline=match.accept_deadline,
        accepted_count=accepted,
        pending_count=pending,
        declined_count=declined,
        seconds_remaining=seconds_remaining,
        all_accepted=(pending == 0 and declined == 0 and accepted == len(members) and len(members) > 0),
    )


@router.post("/{match_id}/accept", response_model=MatchActionResponse)
def accept_match(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchActionResponse:
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증 후 매칭을 이용할 수 있습니다.",
        )

    match = _get_match_or_404(db, match_id)
    _expire_if_needed(db, match)
    db.refresh(match)

    if match.status != "pending_accept":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"수락할 수 있는 상태가 아닙니다. (현재: {match.status})",
        )

    member = _get_member_or_403(db, match_id, current_user.id)
    if member.accept_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 응답했습니다.",
        )

    member.accept_status = "accepted"
    member.responded_at = datetime.now(UTC)
    db.flush()

    pending_left = (
        db.scalar(
            select(func.count())
            .select_from(MatchMember)
            .where(
                MatchMember.match_id == match_id,
                MatchMember.accept_status == "pending",
            )
        )
        or 0
    )

    if pending_left == 0:
        match.status = "confirmed"
        match.confirmed_at = datetime.now(UTC)

    db.commit()
    db.refresh(match)

    return MatchActionResponse(
        match_id=match.id,
        status=match.status,
        my_accept_status=member.accept_status,
        message=(
            "수락했습니다."
            if match.status == "pending_accept"
            else "전원 수락. 매칭이 확정되었습니다."
        ),
    )


@router.post("/{match_id}/decline", response_model=MatchActionResponse)
def decline_match(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchActionResponse:
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증 후 매칭을 이용할 수 있습니다.",
        )

    match = _get_match_or_404(db, match_id)
    _expire_if_needed(db, match)
    db.refresh(match)

    if match.status != "pending_accept":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"거절할 수 있는 상태가 아닙니다. (현재: {match.status})",
        )

    member = _get_member_or_403(db, match_id, current_user.id)
    if member.accept_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 응답했습니다.",
        )

    member.accept_status = "declined"
    member.responded_at = datetime.now(UTC)
    cancel_match_and_requeue(db, match)

    return MatchActionResponse(
        match_id=match.id,
        status="cancelled",
        my_accept_status="declined",
        message="거절했습니다. 매칭이 취소되고 대기열로 돌아갑니다.",
    )
