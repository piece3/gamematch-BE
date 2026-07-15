import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.match import Match, MatchMember
from app.models.match_evaluation import MatchEvaluation
from app.services.manner import finalize_missing_evaluations
from app.services.matchmaking import cancel_match_and_requeue

logger = logging.getLogger(__name__)
JOB_BATCH_SIZE = 100


def expire_pending_matches(db: Session) -> int:
    matches = db.scalars(
        select(Match)
        .where(
            Match.status == "pending_accept",
            Match.accept_deadline.is_not(None),
            Match.accept_deadline <= datetime.now(UTC),
        )
        .order_by(Match.accept_deadline)
        .limit(JOB_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).all()
    for match in matches:
        cancel_match_and_requeue(db, match)
    db.commit()
    return len(matches)


def finalize_overdue_evaluations(db: Session) -> int:
    member_count = (
        select(func.count())
        .select_from(MatchMember)
        .where(MatchMember.match_id == Match.id)
        .correlate(Match)
        .scalar_subquery()
    )
    evaluation_count = (
        select(func.count())
        .select_from(MatchEvaluation)
        .where(MatchEvaluation.match_id == Match.id)
        .correlate(Match)
        .scalar_subquery()
    )
    matches = db.scalars(
        select(Match)
        .where(
            Match.status == "completed",
            Match.evaluation_deadline.is_not(None),
            Match.evaluation_deadline <= datetime.now(UTC),
            evaluation_count < member_count * (member_count - 1),
        )
        .order_by(Match.evaluation_deadline)
        .limit(JOB_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).all()
    inserted = sum(
        finalize_missing_evaluations(db, match)
        for match in matches
    )
    db.commit()
    return inserted


def run_maintenance(db: Session) -> tuple[int, int]:
    expired_matches = expire_pending_matches(db)
    auto_evaluations = finalize_overdue_evaluations(db)
    return expired_matches, auto_evaluations


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        expired, evaluations = run_maintenance(db)
    logger.info(
        "Maintenance complete: expired_matches=%d auto_evaluations=%d",
        expired,
        evaluations,
    )


if __name__ == "__main__":
    main()
