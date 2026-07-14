from datetime import UTC, datetime, timedelta
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.match import Match, MatchMember
from app.models.queue_entry import QueueEntry

ACCEPT_TIMEOUT_SECONDS = 30

TIER_RANK: dict[str, int] = {
    "UN_RANKED": 3,
    "IRON": 1,
    "BRONZE": 2,
    "SILVER": 3,
    "GOLD": 4,
    "PLATINUM": 5,
    "EMERALD": 6,
    "DIAMOND": 7,
    "MASTER": 8,
    "GRANDMASTER": 9,
    "CHALLENGER": 10,
}

REQUIRED_ROLES = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
FLEX_POSITIONS = {"ANYTHING"}


def tier_to_rank(tier: str) -> int:
    try:
        return TIER_RANK[tier]
    except KeyError as exc:
        raise ValueError(f"Unknown tier: {tier}") from exc


def allowed_tier_delta(elapsed_seconds: int) -> int:
    if elapsed_seconds < 30:
        return 0
    if elapsed_seconds < 60:
        return 1
    if elapsed_seconds < 90:
        return 3
    return 4


def is_tier_compatible(my_rank: int, other_rank: int, elapsed_seconds: int) -> bool:
    delta = allowed_tier_delta(elapsed_seconds)
    return abs(my_rank - other_rank) <= delta


def calc_elapsed_seconds(joined_at: datetime) -> int:
    now = datetime.now(UTC)
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=UTC)
    return max(0, int((now - joined_at).total_seconds()))


def can_assign_roles(entries: list) -> dict[int, str] | None:
    """5명 QueueEntry에 TOP~SUPPORT 역할을 한 명씩 배정. 불가 시 None."""
    if len(entries) != 5:
        return None

    candidates: dict[int, list[str]] = {}
    for entry in entries:
        if entry.position in FLEX_POSITIONS:
            candidates[entry.user_id] = list(REQUIRED_ROLES)
        elif entry.position in REQUIRED_ROLES:
            candidates[entry.user_id] = [entry.position]
        else:
            return None

    assignment: dict[int, str] = {}
    used: set[str] = set()
    order = sorted(candidates.keys(), key=lambda uid: len(candidates[uid]))

    def dfs(idx: int) -> bool:
        if idx == len(order):
            return True
        uid = order[idx]
        for role in candidates[uid]:
            if role in used:
                continue
            used.add(role)
            assignment[uid] = role
            if dfs(idx + 1):
                return True
            used.remove(role)
            del assignment[uid]
        return False

    if dfs(0):
        return assignment
    return None


def play_style_score(styles_a: list[str] | None, styles_b: list[str] | None) -> int:
    if not styles_a or not styles_b:
        return 0
    return len(set(styles_a) & set(styles_b))


def group_tier_compatible(entries: list, elapsed_by_user_id: dict[int, int]) -> bool:
    max_elapsed = max(elapsed_by_user_id[e.user_id] for e in entries)
    delta = allowed_tier_delta(max_elapsed)
    ranks = [e.tier_rank for e in entries]
    return max(ranks) - min(ranks) <= delta


def try_form_match(db: Session, game: str = "lol") -> Match | None:
    waiting = db.scalars(
        select(QueueEntry)
        .where(QueueEntry.status == "waiting", QueueEntry.game == game)
        .order_by(QueueEntry.joined_at.asc())
    ).all()

    if len(waiting) < 5:
        return None

    elapsed_map = {e.user_id: calc_elapsed_seconds(e.joined_at) for e in waiting}

    for group in combinations(waiting, 5):
        entries = list(group)
        if not group_tier_compatible(entries, elapsed_map):
            continue
        roles = can_assign_roles(entries)
        if roles is None:
            continue
        return _create_match_session(db, entries, roles)

    return None


def _create_match_session(db: Session, entries: list, roles: dict[int, str]) -> Match:
    now = datetime.now(UTC)
    match = Match(
        game="lol",
        status="pending_accept",
        accept_deadline=now + timedelta(seconds=ACCEPT_TIMEOUT_SECONDS),
    )
    db.add(match)
    db.flush()

    for entry in entries:
        db.add(
            MatchMember(
                match_id=match.id,
                user_id=entry.user_id,
                tier=entry.tier,
                tier_rank=entry.tier_rank,
                position=entry.position,
                play_styles=entry.play_styles,
                assigned_role=roles[entry.user_id],
                accept_status="pending",
            )
        )
        entry.status = "matched"

    db.commit()
    db.refresh(match)
    return match


def cancel_match_and_requeue(db: Session, match: Match) -> None:
    """거절·타임아웃 시 매칭 취소 후 멤버를 큐(waiting)로 되돌린다."""
    match.status = "cancelled"

    members = db.scalars(
        select(MatchMember).where(MatchMember.match_id == match.id)
    ).all()

    for member in members:
        entry = db.scalar(select(QueueEntry).where(QueueEntry.user_id == member.user_id))
        if entry is not None:
            entry.status = "waiting"

    db.commit()
