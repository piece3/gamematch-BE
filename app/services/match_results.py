"""Sync lobby match results from one player's Riot match history."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lol_profile import LolProfile
from app.models.match import Match, MatchMember
from app.models.user_match_record import MAX_RECORDS_PER_USER, UserMatchRecord
from app.schemas.queue import GAME_MODE_QUEUE_IDS, GameMode
from app.services.riot import RiotApiError, fetch_match_detail, fetch_recent_match_ids

logger = logging.getLogger(__name__)

MIN_TEAM_OVERLAP = 2
RESULT_LOOKAHEAD = timedelta(hours=3)
RESULT_LOOKBEHIND = timedelta(minutes=5)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _trim_user_records(db: Session, user_id: int) -> None:
    records = db.scalars(
        select(UserMatchRecord)
        .where(UserMatchRecord.user_id == user_id)
        .order_by(UserMatchRecord.played_at.desc(), UserMatchRecord.id.desc())
    ).all()
    for stale in records[MAX_RECORDS_PER_USER:]:
        db.delete(stale)


def sync_match_result_from_riot(
    db: Session,
    match: Match,
    *,
    preferred_user_id: int | None = None,
) -> bool:
    """
    Look up one member's recent Riot match, verify teammate overlap, then
    write win/loss rows for every matched member (max 5 history rows each).
    """
    if match.result_status == "synced" and match.riot_match_id:
        return True

    members = db.scalars(
        select(MatchMember).where(MatchMember.match_id == match.id)
    ).all()
    member_user_ids = [member.user_id for member in members]
    profiles = db.scalars(
        select(LolProfile).where(LolProfile.user_id.in_(member_user_ids))
    ).all()
    puuid_by_user = {
        profile.user_id: profile.puuid
        for profile in profiles
        if profile.puuid
    }
    if not puuid_by_user:
        match.result_status = "unresolved"
        return False

    lookup_user_id = preferred_user_id if preferred_user_id in puuid_by_user else None
    if lookup_user_id is None:
        lookup_user_id = next(iter(puuid_by_user))
    lookup_puuid = puuid_by_user[lookup_user_id]

    try:
        game_mode = GameMode(match.game_mode)
    except ValueError:
        match.result_status = "unresolved"
        return False

    queue_ids = GAME_MODE_QUEUE_IDS[game_mode]
    confirmed_at = _as_utc(match.confirmed_at) or _as_utc(match.created_at)
    completed_at = _as_utc(match.completed_at) or datetime.now(UTC)
    if confirmed_at is None:
        match.result_status = "unresolved"
        return False

    start_ms = int((confirmed_at - RESULT_LOOKBEHIND).timestamp() * 1000)
    end_ms = int((completed_at + RESULT_LOOKAHEAD).timestamp() * 1000)
    member_puuids = set(puuid_by_user.values())

    try:
        candidate_ids: list[str] = []
        for queue_id in queue_ids:
            candidate_ids.extend(
                fetch_recent_match_ids(
                    lookup_puuid,
                    queue_id=queue_id,
                    count=5,
                    start_time_ms=start_ms,
                    end_time_ms=end_ms,
                )
            )
        # Preserve order while de-duplicating.
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for match_id in candidate_ids:
            if match_id not in seen:
                seen.add(match_id)
                ordered_ids.append(match_id)

        for riot_match_id in ordered_ids[:5]:
            detail = fetch_match_detail(riot_match_id)
            info = detail.get("info") or {}
            participants = info.get("participants") or []
            if not isinstance(participants, list):
                continue

            by_puuid = {
                participant.get("puuid"): participant
                for participant in participants
                if isinstance(participant, dict) and participant.get("puuid")
            }
            overlap = member_puuids & set(by_puuid)
            if len(overlap) < MIN_TEAM_OVERLAP:
                continue

            lookup_participant = by_puuid.get(lookup_puuid)
            if lookup_participant is None:
                continue
            team_id = lookup_participant.get("teamId")
            same_team_overlap = {
                puuid
                for puuid in overlap
                if by_puuid[puuid].get("teamId") == team_id
            }
            if len(same_team_overlap) < MIN_TEAM_OVERLAP:
                continue

            game_start = info.get("gameStartTimestamp")
            played_at = (
                datetime.fromtimestamp(game_start / 1000, tz=UTC)
                if isinstance(game_start, (int, float))
                else completed_at
            )

            for user_id, puuid in puuid_by_user.items():
                participant = by_puuid.get(puuid)
                if participant is None:
                    continue
                existing = db.scalar(
                    select(UserMatchRecord).where(
                        UserMatchRecord.user_id == user_id,
                        UserMatchRecord.riot_match_id == riot_match_id,
                    )
                )
                if existing is not None:
                    continue
                db.add(
                    UserMatchRecord(
                        user_id=user_id,
                        match_id=match.id,
                        riot_match_id=riot_match_id,
                        game_mode=match.game_mode,
                        won=bool(participant.get("win")),
                        played_at=played_at,
                    )
                )
                db.flush()
                _trim_user_records(db, user_id)

            match.riot_match_id = riot_match_id
            match.result_status = "synced"
            return True
    except RiotApiError:
        logger.exception(
            "Failed to sync Riot result for match_id=%s", match.id
        )

    match.result_status = "unresolved"
    return False


def list_user_match_records(
    db: Session,
    user_id: int,
    *,
    limit: int = MAX_RECORDS_PER_USER,
) -> list[UserMatchRecord]:
    return list(
        db.scalars(
            select(UserMatchRecord)
            .where(UserMatchRecord.user_id == user_id)
            .order_by(UserMatchRecord.played_at.desc(), UserMatchRecord.id.desc())
            .limit(min(limit, MAX_RECORDS_PER_USER))
        ).all()
    )
