from datetime import UTC, datetime, timedelta
from itertools import combinations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.match import Match, MatchMember
from app.models.queue_entry import QueueEntry

ACCEPT_TIMEOUT_SECONDS = 30
MAX_MATCH_CANDIDATES = 20

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
            secondary = getattr(entry, "secondary_position", None)
            if secondary in FLEX_POSITIONS:
                candidates[entry.user_id].extend(
                    role for role in REQUIRED_ROLES if role != entry.position
                )
            elif (
                secondary in REQUIRED_ROLES
                and secondary not in candidates[entry.user_id]
            ):
                candidates[entry.user_id].append(secondary)
        else:
            return None

    assignment: dict[int, str] = {}
    used: set[str] = set()
    order = sorted(candidates.keys(), key=lambda uid: len(candidates[uid]))
    best_assignment: dict[int, str] | None = None
    best_score = -1

    def preference_score(uid: int, role: str) -> int:
        entry = next(item for item in entries if item.user_id == uid)
        if entry.position == role:
            return 2
        if getattr(entry, "secondary_position", None) == role:
            return 1
        return 0

    def dfs(idx: int, score: int) -> None:
        nonlocal best_assignment, best_score
        if idx == len(order):
            if score > best_score:
                best_score = score
                best_assignment = assignment.copy()
            return
        uid = order[idx]
        for role in candidates[uid]:
            if role in used:
                continue
            used.add(role)
            assignment[uid] = role
            dfs(idx + 1, score + preference_score(uid, role))
            used.remove(role)
            del assignment[uid]

    dfs(0, 0)
    return best_assignment


def play_style_score(styles_a: list[str] | None, styles_b: list[str] | None) -> int:
    if not styles_a or not styles_b:
        return 0
    return len(set(styles_a) & set(styles_b))


def group_tier_compatible(entries: list, elapsed_by_user_id: dict[int, int]) -> bool:
    max_elapsed = max(elapsed_by_user_id[e.user_id] for e in entries)
    delta = allowed_tier_delta(max_elapsed)
    ranks = [e.tier_rank for e in entries]
    return max(ranks) - min(ranks) <= delta


def _group_style_score(entries: list[QueueEntry]) -> int:
    return sum(
        play_style_score(left.play_styles, right.play_styles)
        for left, right in combinations(entries, 2)
    )


def try_form_match(db: Session, game: str = "lol") -> Match | None:
    lock_acquired = db.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": f"matchmaking:{game}"},
    )
    if not lock_acquired:
        return None

    waiting = db.scalars(
        select(QueueEntry)
        .where(QueueEntry.status == "waiting", QueueEntry.game == game)
        .order_by(QueueEntry.joined_at.asc())
        .limit(MAX_MATCH_CANDIDATES)
        .with_for_update(skip_locked=True)
    ).all()

    if len(waiting) < 5:
        return None

    elapsed_map = {e.user_id: calc_elapsed_seconds(e.joined_at) for e in waiting}

    best: tuple[tuple[int, int, int], list[QueueEntry], dict[int, str]] | None = None
    for group in combinations(waiting, 5):
        entries = list(group)
        if not group_tier_compatible(entries, elapsed_map):
            continue
        roles = can_assign_roles(entries)
        if roles is None:
            continue
        ranks = [entry.tier_rank for entry in entries]
        score = (
            _group_style_score(entries),
            -(max(ranks) - min(ranks)),
            sum(elapsed_map[entry.user_id] for entry in entries),
        )
        if best is None or score > best[0]:
            best = (score, entries, roles)

    if best is None:
        return None
    return _create_match_session(db, best[1], best[2], game)


def _create_match_session(
    db: Session,
    entries: list,
    roles: dict[int, str],
    game: str,
) -> Match:
    now = datetime.now(UTC)
    match = Match(
        game=game,
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


def cancel_match_and_requeue(
    db: Session,
    match: Match,
    *,
    declined_user_id: int | None = None,
) -> None:
    """Cancel a match; remove a decliner and requeue everyone else."""
    if match.status != "pending_accept":
        return
    match.status = "cancelled"

    members = db.scalars(
        select(MatchMember)
        .where(MatchMember.match_id == match.id)
        .with_for_update()
    ).all()

    for member in members:
        entry = db.scalar(
            select(QueueEntry)
            .where(QueueEntry.user_id == member.user_id)
            .with_for_update()
        )
        if entry is None:
            continue
        if member.user_id == declined_user_id:
            db.delete(entry)
        else:
            entry.status = "waiting"
