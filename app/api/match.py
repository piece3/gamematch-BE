from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_verified_user
from app.database import get_db
from app.models.fc_online_match_record import FcOnlineMatchRecord
from app.models.fc_online_profile import FcOnlineProfile
from app.models.lol_profile import LolProfile
from app.models.match import Match, MatchMember
from app.models.match_evaluation import MatchEvaluation
from app.models.match_quick_message import MatchQuickMessage
from app.models.queue_entry import QueueEntry
from app.models.user import User
from app.schemas.match import (
    AcceptStatusResponse,
    EvaluationStatusResponse,
    MatchActionResponse,
    MatchDetailResponse,
    MatchEvaluateRequest,
    MatchEvaluateResponse,
    MatchHistoryItem,
    MatchHistoryResponse,
    MatchMemberSummary,
    MatchMembersResponse,
    PersonalRecordItem,
    PersonalRecordsResponse,
    QuickMessageItem,
    QuickMessageListResponse,
    QuickMessageSendRequest,
)
from app.schemas.queue import (
    QueueJoinRequest,
    QueueJoinResponse,
    QueueStatusResponse,
)
from app.services.manner import (
    EVALUATION_TIMEOUT_HOURS,
    apply_manner_deltas,
    count_evaluations_by_evaluator,
    evaluation_deadline_passed,
    validate_evaluation_targets,
)
from app.services.match_results import (
    list_user_match_records,
    sync_match_result_from_fc_online,
    sync_match_result_from_riot,
)
from app.services.matchmaking import (
    allowed_tier_delta,
    calc_elapsed_seconds,
    cancel_match_and_requeue,
    tier_to_rank,
    try_form_match,
)
from app.models.user_match_record import MAX_RECORDS_PER_USER, UserMatchRecord

router = APIRouter(prefix="/match", tags=["match"])


def _get_lol_profile_or_400(db: Session, user_id: int) -> LolProfile:
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user_id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="롤 프로필이 없습니다. 먼저 /profile/game-settings 를 설정하세요.",
        )
    return profile


def _get_fc_profile_or_400(db: Session, user_id: int) -> FcOnlineProfile:
    profile = db.scalar(
        select(FcOnlineProfile).where(FcOnlineProfile.user_id == user_id)
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="FC 온라인 프로필이 없습니다. 먼저 /profile/fc-online/sync를 호출하세요.",
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


def _get_match_for_update_or_404(db: Session, match_id: int) -> Match:
    match = db.scalar(
        select(Match).where(Match.id == match_id).with_for_update()
    )
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


def _get_member_for_update_or_403(
    db: Session, match_id: int, user_id: int
) -> MatchMember:
    member = db.scalar(
        select(MatchMember)
        .where(
            MatchMember.match_id == match_id,
            MatchMember.user_id == user_id,
        )
        .with_for_update()
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 매칭의 멤버가 아닙니다.",
        )
    return member


def _member_user_ids(db: Session, match_id: int) -> set[int]:
    members = db.scalars(
        select(MatchMember).where(MatchMember.match_id == match_id)
    ).all()
    return {m.user_id for m in members}


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
        locked_match = _get_match_for_update_or_404(db, match.id)
        cancel_match_and_requeue(db, locked_match)
        db.commit()


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


def _find_live_active_match_for_user(
    db: Session,
    user_id: int,
) -> Match | None:
    match = _find_active_match_for_user(db, user_id)
    if match is None:
        return None
    _expire_if_needed(db, match)
    db.refresh(match)
    if match.status in ("pending_accept", "confirmed"):
        return match
    return None


def _to_match_detail(match: Match, member: MatchMember | None) -> MatchDetailResponse:
    return MatchDetailResponse(
        id=match.id,
        game=match.game,
        game_mode=match.game_mode,
        party_size=match.party_size,
        status=match.status,
        accept_deadline=match.accept_deadline,
        created_at=match.created_at,
        confirmed_at=match.confirmed_at,
        completed_at=match.completed_at,
        evaluation_deadline=match.evaluation_deadline,
        my_accept_status=member.accept_status if member else None,
        riot_match_id=match.riot_match_id,
        nexon_match_id=match.nexon_match_id,
        result_status=match.result_status,
    )


@router.post("/queue/join", response_model=QueueJoinResponse, status_code=status.HTTP_201_CREATED)
def join_queue(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: QueueJoinRequest = QueueJoinRequest(),
) -> QueueEntry:
    active_match = _find_live_active_match_for_user(db, current_user.id)
    if active_match is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"이미 활성 매칭이 있습니다. match_id={active_match.id}, "
                f"status={active_match.status}"
            ),
        )

    existing = db.scalar(
        select(QueueEntry)
        .where(QueueEntry.user_id == current_user.id)
        .with_for_update()
    )
    if existing is not None and existing.status == "waiting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 매칭 대기 중입니다.",
        )
    if existing is not None and existing.status == "matched":
        # The queue row is locked; do not acquire match locks in the opposite
        # order. The maintenance/active endpoints handle deadline expiry.
        active_match = _find_active_match_for_user(db, current_user.id)
        if active_match is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"이미 활성 매칭이 있습니다. match_id={active_match.id}, "
                    f"status={active_match.status}"
                ),
            )

    if existing is None:
        entry = QueueEntry(user_id=current_user.id)
        db.add(entry)
    else:
        # A matched row without an active match is stale after a prior crash.
        entry = existing

    entry.game = payload.game.value
    entry.game_mode = payload.game_mode
    entry.party_size = payload.party_size
    if entry.game == "lol":
        lol_profile = _get_lol_profile_or_400(db, current_user.id)
        entry.tier = lol_profile.tier
        entry.tier_rank = tier_to_rank(lol_profile.tier)
        entry.position = lol_profile.primary_position
        entry.secondary_position = lol_profile.secondary_position
        entry.play_styles = lol_profile.play_styles or []
    else:
        fc_profile = _get_fc_profile_or_400(db, current_user.id)
        if entry.game_mode == "OFFICIAL_1V1":
            entry.tier = fc_profile.division_1v1_name or "UN_RANKED"
            entry.tier_rank = fc_profile.division_1v1_rank or 0
        else:
            entry.tier = fc_profile.division_2v2_name or "UN_RANKED"
            entry.tier_rank = fc_profile.division_2v2_rank or 0
        entry.position = "ANYTHING"
        entry.secondary_position = "ANYTHING"
        entry.play_styles = []
    entry.status = "waiting"
    entry.joined_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 매칭 대기 중이거나 활성 매칭이 있습니다.",
        ) from exc
    db.refresh(entry)

    try_form_match(db, game=entry.game, game_mode=entry.game_mode)
    db.refresh(entry)
    return entry


@router.get("/queue/status", response_model=QueueStatusResponse)
def queue_status(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QueueStatusResponse:
    try_form_match(db)
    try_form_match(db, game="fc_online")

    active_match = _find_live_active_match_for_user(db, current_user.id)
    if active_match is not None:
        return QueueStatusResponse(
            in_queue=False,
            match_id=active_match.id,
            match_status=active_match.status,
            message=(
                "매칭이 성사되었습니다. 수락/거절을 진행하세요."
                if active_match.status == "pending_accept"
                else "매칭이 확정되었습니다."
            ),
        )

    entry = db.scalar(
        select(QueueEntry)
        .where(QueueEntry.user_id == current_user.id)
        .with_for_update()
    )
    if entry is None:
        return QueueStatusResponse(in_queue=False, message="매칭 대기 중이 아닙니다.")
    if entry.status == "matched":
        # Matchmaking may have committed after the first active-match lookup.
        active_match = _find_active_match_for_user(db, current_user.id)
        if active_match is not None:
            return QueueStatusResponse(
                in_queue=False,
                match_id=active_match.id,
                match_status=active_match.status,
                message=(
                    "매칭이 성사되었습니다. 수락/거절을 진행하세요."
                    if active_match.status == "pending_accept"
                    else "매칭이 확정되었습니다."
                ),
            )
        # No active match owns the locked row, so repair it in place.
        entry.status = "waiting"
        entry.joined_at = datetime.now(UTC)
        db.commit()
        db.refresh(entry)

    elapsed = calc_elapsed_seconds(entry.joined_at)
    delta = allowed_tier_delta(elapsed)
    waiting_count = (
        db.scalar(
            select(func.count())
            .select_from(QueueEntry)
            .where(
                QueueEntry.status == "waiting",
                QueueEntry.game == entry.game,
                QueueEntry.game_mode == entry.game_mode,
            )
        )
        or 0
    )

    return QueueStatusResponse(
        in_queue=True,
        status=entry.status,
        game=entry.game,
        game_mode=entry.game_mode,
        party_size=entry.party_size,
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
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    entry = db.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == current_user.id,
            QueueEntry.status == "waiting",
        ).with_for_update()
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="매칭 대기 중이 아닙니다.",
        )

    db.delete(entry)
    db.commit()


@router.get("/history", response_model=MatchHistoryResponse)
def match_history(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MatchHistoryResponse:
    memberships = db.scalars(
        select(MatchMember)
        .join(Match, Match.id == MatchMember.match_id)
        .where(
            MatchMember.user_id == current_user.id,
            Match.status.in_(("confirmed", "completed")),
        )
        .order_by(func.coalesce(Match.completed_at, Match.confirmed_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()

    items: list[MatchHistoryItem] = []
    for membership in memberships:
        match = db.get(Match, membership.match_id)
        if match is None:
            continue
        member_count = (
            db.scalar(
                select(func.count())
                .select_from(MatchMember)
                .where(MatchMember.match_id == match.id)
            )
            or 0
        )
        submitted = (
            count_evaluations_by_evaluator(
                db,
                match.id,
                current_user.id,
                manual_only=True,
            )
            > 0
        )
        if match.game == "lol":
            won = db.scalar(
                select(UserMatchRecord.won).where(
                    UserMatchRecord.user_id == current_user.id,
                    UserMatchRecord.match_id == match.id,
                )
            )
        else:
            fc_result = db.scalar(
                select(FcOnlineMatchRecord.result).where(
                    FcOnlineMatchRecord.user_id == current_user.id,
                    FcOnlineMatchRecord.match_id == match.id,
                )
            )
            won = None if fc_result is None or fc_result == "DRAW" else fc_result == "WIN"
        items.append(
            MatchHistoryItem(
                match_id=match.id,
                game=match.game,
                game_mode=match.game_mode,
                status=match.status,
                my_assigned_role=membership.assigned_role,
                my_tier=membership.tier,
                member_count=member_count,
                confirmed_at=match.confirmed_at,
                completed_at=match.completed_at,
                evaluation_submitted=submitted,
                won=won,
                result_status=match.result_status,
            )
        )

    total = (
        db.scalar(
            select(func.count())
            .select_from(MatchMember)
            .join(Match, Match.id == MatchMember.match_id)
            .where(
                MatchMember.user_id == current_user.id,
                Match.status.in_(("confirmed", "completed")),
            )
        )
        or 0
    )

    return MatchHistoryResponse(total=total, items=items)


@router.get("/records", response_model=PersonalRecordsResponse)
def personal_match_records(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PersonalRecordsResponse:
    """인당 최근 전적 최대 5개 (Riot 동기화 결과)."""
    records = list_user_match_records(db, current_user.id)
    return PersonalRecordsResponse(
        total=len(records),
        limit=MAX_RECORDS_PER_USER,
        items=[
            PersonalRecordItem(
                match_id=record.match_id,
                riot_match_id=record.riot_match_id,
                game_mode=record.game_mode,
                won=record.won,
                played_at=record.played_at,
            )
            for record in records
        ],
    )


@router.get("/active", response_model=MatchDetailResponse | None)
def get_active_match(
    current_user: Annotated[User, Depends(get_current_verified_user)],
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
    return _to_match_detail(match, member)


@router.get("/{match_id}", response_model=MatchDetailResponse)
def get_match(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchDetailResponse:
    match = _get_match_or_404(db, match_id)
    member = _get_member_or_403(db, match_id, current_user.id)
    _expire_if_needed(db, match)
    db.refresh(match)
    return _to_match_detail(match, member)


@router.get("/{match_id}/members", response_model=MatchMembersResponse)
def get_match_members(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
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


@router.post("/{match_id}/quick-messages", response_model=QuickMessageItem)
def send_quick_message(
    match_id: int,
    payload: QuickMessageSendRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QuickMessageItem:
    match = _get_match_or_404(db, match_id)
    _get_member_or_403(db, match_id, current_user.id)
    if match.status not in ("pending_accept", "confirmed", "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="퀵 메시지를 보낼 수 있는 매칭 상태가 아닙니다.",
        )

    message = MatchQuickMessage(
        match_id=match_id,
        user_id=current_user.id,
        message=payload.message.value,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return QuickMessageItem(
        id=message.id,
        match_id=message.match_id,
        user_id=message.user_id,
        nickname=current_user.nickname,
        message=message.message,
        created_at=message.created_at,
    )


@router.get("/{match_id}/quick-messages", response_model=QuickMessageListResponse)
def list_quick_messages(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> QuickMessageListResponse:
    _get_match_or_404(db, match_id)
    _get_member_or_403(db, match_id, current_user.id)
    rows = db.scalars(
        select(MatchQuickMessage)
        .where(MatchQuickMessage.match_id == match_id)
        .order_by(MatchQuickMessage.created_at.desc(), MatchQuickMessage.id.desc())
        .limit(limit)
    ).all()
    items = []
    for row in reversed(rows):
        sender = db.get(User, row.user_id)
        items.append(
            QuickMessageItem(
                id=row.id,
                match_id=row.match_id,
                user_id=row.user_id,
                nickname=sender.nickname if sender else f"user-{row.user_id}",
                message=row.message,
                created_at=row.created_at,
            )
        )
    return QuickMessageListResponse(total=len(items), items=items)


@router.get("/{match_id}/accept-status", response_model=AcceptStatusResponse)
def accept_status(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
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
        all_accepted=(
            pending == 0 and declined == 0 and accepted == len(members) and len(members) > 0
        ),
    )


@router.post("/{match_id}/accept", response_model=MatchActionResponse)
def accept_match(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchActionResponse:
    match = _get_match_for_update_or_404(db, match_id)
    _expire_if_needed(db, match)
    db.refresh(match)

    if match.status != "pending_accept":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"수락할 수 있는 상태가 아닙니다. (현재: {match.status})",
        )

    member = _get_member_for_update_or_403(db, match_id, current_user.id)
    if member.accept_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 응답했습니다.",
        )

    member.accept_status = "accepted"
    member.responded_at = datetime.now(UTC)
    db.flush()

    members = db.scalars(
        select(MatchMember)
        .where(MatchMember.match_id == match_id)
        .with_for_update()
    ).all()
    accepted_count = sum(m.accept_status == "accepted" for m in members)
    declined_count = sum(m.accept_status == "declined" for m in members)

    expected_members = 5 if match.game == "lol" else 2
    if (
        len(members) == expected_members
        and accepted_count == expected_members
        and declined_count == 0
    ):
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
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchActionResponse:
    match = _get_match_for_update_or_404(db, match_id)
    _expire_if_needed(db, match)
    db.refresh(match)

    if match.status != "pending_accept":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"거절할 수 있는 상태가 아닙니다. (현재: {match.status})",
        )

    member = _get_member_for_update_or_403(db, match_id, current_user.id)
    if member.accept_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 응답했습니다.",
        )

    member.accept_status = "declined"
    member.responded_at = datetime.now(UTC)
    cancel_match_and_requeue(
        db,
        match,
        declined_user_id=current_user.id,
    )
    db.commit()

    return MatchActionResponse(
        match_id=match.id,
        status="cancelled",
        my_accept_status="declined",
        message="거절했습니다. 본인은 큐에서 제외되고 나머지 멤버는 대기열로 돌아갑니다.",
    )


@router.post("/{match_id}/complete", response_model=MatchDetailResponse)
def complete_match(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchDetailResponse:
    match = _get_match_for_update_or_404(db, match_id)
    member = _get_member_for_update_or_403(db, match_id, current_user.id)

    if match.status == "completed":
        return _to_match_detail(match, member)

    if match.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirmed 상태의 매칭만 완료할 수 있습니다.",
        )

    now = datetime.now(UTC)
    match.status = "completed"
    match.completed_at = now
    match.completed_by_user_id = current_user.id
    match.evaluation_deadline = now + timedelta(hours=EVALUATION_TIMEOUT_HOURS)

    # 완료 후 재참가 가능하도록 큐 entry 정리
    member_ids = _member_user_ids(db, match_id)
    for uid in member_ids:
        entry = db.scalar(select(QueueEntry).where(QueueEntry.user_id == uid))
        if entry is not None:
            db.delete(entry)

    if match.game == "lol":
        sync_match_result_from_riot(
            db,
            match,
            preferred_user_id=current_user.id,
        )
    else:
        sync_match_result_from_fc_online(
            db,
            match,
            preferred_user_id=current_user.id,
        )
    db.commit()
    db.refresh(match)
    return _to_match_detail(match, member)


@router.post("/{match_id}/evaluate", response_model=MatchEvaluateResponse)
def evaluate_match(
    match_id: int,
    payload: MatchEvaluateRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MatchEvaluateResponse:
    match = _get_match_for_update_or_404(db, match_id)
    _get_member_or_403(db, match_id, current_user.id)

    if match.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="게임 완료 후에만 평가할 수 있습니다.",
        )

    if evaluation_deadline_passed(match):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="평가 기한이 지났습니다. 미제출분은 3점으로 기록되었습니다.",
        )

    existing = count_evaluations_by_evaluator(db, match_id, current_user.id)
    if existing > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 평가를 제출했습니다.",
        )

    member_ids = _member_user_ids(db, match_id)
    targets = [
        {"target_user_id": item.target_user_id, "manner_delta": item.manner_delta}
        for item in payload.evaluations
    ]
    try:
        validate_evaluation_targets(member_ids, current_user.id, targets)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    for item in payload.evaluations:
        db.add(
            MatchEvaluation(
                match_id=match_id,
                evaluator_user_id=current_user.id,
                target_user_id=item.target_user_id,
                manner_delta=item.manner_delta,
                is_auto=False,
            )
        )

    apply_manner_deltas(
        db,
        {
            item.target_user_id: item.manner_delta
            for item in payload.evaluations
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 평가를 제출했습니다.",
        ) from exc

    return MatchEvaluateResponse(
        match_id=match_id,
        submitted_count=len(payload.evaluations),
        message="평가가 제출되었습니다.",
    )


@router.get("/{match_id}/evaluations/status", response_model=EvaluationStatusResponse)
def evaluation_status(
    match_id: int,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[Session, Depends(get_db)],
) -> EvaluationStatusResponse:
    match = _get_match_or_404(db, match_id)
    _get_member_or_403(db, match_id, current_user.id)

    member_count = len(_member_user_ids(db, match_id))
    required = max(0, member_count - 1)
    submitted = count_evaluations_by_evaluator(
        db,
        match_id,
        current_user.id,
        manual_only=True,
    )

    seconds_remaining = 0
    if match.evaluation_deadline is not None and match.status == "completed":
        deadline = match.evaluation_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        seconds_remaining = max(0, int((deadline - datetime.now(UTC)).total_seconds()))

    return EvaluationStatusResponse(
        match_id=match.id,
        required_count=required,
        submitted_count=min(submitted, required),
        is_complete=submitted >= required and required > 0,
        evaluation_deadline=match.evaluation_deadline,
        seconds_remaining=seconds_remaining,
    )
