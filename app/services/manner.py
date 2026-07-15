from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.match import Match, MatchMember
from app.models.match_evaluation import MatchEvaluation

MANNER_MIN = 0.0
MANNER_MAX = 5.0
MANNER_DEFAULT = 3.0
EVALUATION_TIMEOUT_HOURS = 24
NEUTRAL_DELTA = 0  # 미제출 = 3점
ALLOWED_DELTAS = {-1, 0, 1}


def apply_manner_delta(current: float, delta: int, weight: float = 0.2) -> float:
    """weight=0.2 예: 3.0에서 +1 받으면 3.2. delta=0 이면 점수 불변."""
    new_score = current + delta * weight
    return max(MANNER_MIN, min(MANNER_MAX, round(new_score, 2)))


def finalize_missing_evaluations(db: Session, match: Match) -> int:
    """
    평가 기한이 지났는데 제출하지 않은 멤버에게
    팀원 전원에 대한 manner_delta=0 (3점) 자동 기록.
    반환: 새로 INSERT한 row 수.
    """
    if match.status != "completed":
        return 0
    if match.evaluation_deadline is None or match.completed_at is None:
        return 0

    now = datetime.now(UTC)
    deadline = match.evaluation_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if now <= deadline:
        return 0

    members = db.scalars(
        select(MatchMember).where(MatchMember.match_id == match.id)
    ).all()
    member_ids = [m.user_id for m in members]
    inserted = 0

    for evaluator_id in member_ids:
        already = db.scalar(
            select(MatchEvaluation).where(
                MatchEvaluation.match_id == match.id,
                MatchEvaluation.evaluator_user_id == evaluator_id,
            )
        )
        if already is not None:
            continue

        for target_id in member_ids:
            if target_id == evaluator_id:
                continue
            db.add(
                MatchEvaluation(
                    match_id=match.id,
                    evaluator_user_id=evaluator_id,
                    target_user_id=target_id,
                    manner_delta=NEUTRAL_DELTA,
                )
            )
            inserted += 1

    if inserted:
        db.commit()
    return inserted


def validate_evaluation_targets(
    member_user_ids: set[int],
    evaluator_id: int,
    targets: list[dict],
) -> None:
    if evaluator_id not in member_user_ids:
        raise ValueError("매칭 멤버만 평가할 수 있습니다.")
    if len(targets) != len(member_user_ids) - 1:
        raise ValueError("본인을 제외한 모든 팀원을 평가해야 합니다.")
    seen: set[int] = set()
    for item in targets:
        target_id = item["target_user_id"]
        if target_id == evaluator_id:
            raise ValueError("본인은 평가할 수 없습니다.")
        if target_id not in member_user_ids:
            raise ValueError("팀원만 평가할 수 있습니다.")
        if target_id in seen:
            raise ValueError("같은 팀원을 중복 평가할 수 없습니다.")
        if item["manner_delta"] not in ALLOWED_DELTAS:
            raise ValueError("manner_delta는 -1, 0, 1 만 가능합니다.")
        seen.add(target_id)


def count_evaluations_by_evaluator(db: Session, match_id: int, evaluator_id: int) -> int:
    rows = db.scalars(
        select(MatchEvaluation).where(
            MatchEvaluation.match_id == match_id,
            MatchEvaluation.evaluator_user_id == evaluator_id,
        )
    ).all()
    return len(rows)


def evaluation_deadline_passed(match: Match) -> bool:
    if match.evaluation_deadline is None:
        return False
    deadline = match.evaluation_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return datetime.now(UTC) > deadline
