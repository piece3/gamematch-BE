from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.maintenance import run_maintenance
from app.models.lol_profile import LolProfile
from app.models.match import Match, MatchMember
from app.models.match_evaluation import MatchEvaluation
from app.models.queue_entry import QueueEntry
from app.services.matchmaking import try_form_match

ROLES = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]


def test_maintenance_creates_neutral_auto_evaluations(
    db: Session,
    user_factory,
) -> None:
    users = [user_factory() for _ in range(5)]
    completed_at = datetime.now(UTC) - timedelta(hours=25)
    match = Match(
        game="lol",
        status="completed",
        completed_at=completed_at,
        evaluation_deadline=completed_at + timedelta(hours=24),
    )
    db.add(match)
    db.flush()
    for user, role in zip(users, ROLES, strict=True):
        db.add(
            MatchMember(
                match_id=match.id,
                user_id=user.id,
                tier="SILVER",
                tier_rank=3,
                position=role,
                assigned_role=role,
                accept_status="accepted",
            )
        )
    db.commit()

    _, inserted = run_maintenance(db)

    evaluations = db.scalars(
        select(MatchEvaluation).where(MatchEvaluation.match_id == match.id)
    ).all()
    assert inserted == 20
    assert len(evaluations) == 20
    assert all(item.is_auto and item.manner_delta == 0 for item in evaluations)


def test_public_ranking_is_private_and_uses_division_and_lp(
    client: TestClient,
    db: Session,
    user_factory,
    auth_headers,
) -> None:
    users = [user_factory(with_profile=True) for _ in range(3)]
    ranks = [
        ("GOLD", 4, "IV", 99),
        ("GOLD", 4, "III", 1),
        ("PLATINUM", 5, "IV", 0),
    ]
    for user, (tier, tier_rank, division, lp) in zip(
        users, ranks, strict=True
    ):
        profile = db.scalar(
            select(LolProfile).where(LolProfile.user_id == user.id)
        )
        assert profile is not None
        profile.puuid = f"puuid-{user.id}"
        profile.riot_id = f"Player{user.id}#KR1"
        profile.tier = tier
        profile.tier_rank = tier_rank
        profile.rank_division = division
        profile.league_points = lp
    db.commit()

    public = client.get("/ranking/lol")
    mine = client.get("/ranking/me", headers=auth_headers(users[1]))

    assert public.status_code == 200
    items = public.json()["items"]
    assert [item["user_id"] for item in items] == [
        users[2].id,
        users[1].id,
        users[0].id,
    ]
    assert "riot_id" not in items[0]
    assert "college" not in items[0]
    assert "department" not in items[0]
    assert mine.status_code == 200
    assert mine.json()["rank"] == 2


def test_concurrent_matchmaking_creates_only_one_match(
    db: Session,
    user_factory,
    session_factory: sessionmaker[Session],
) -> None:
    users = [user_factory(with_profile=True, position=role) for role in ROLES]
    for user, role in zip(users, ROLES, strict=True):
        db.add(
            QueueEntry(
                user_id=user.id,
                game="lol",
                game_mode="SOLO",
                tier="SILVER",
                tier_rank=3,
                position=role,
                secondary_position="ANYTHING",
                play_styles=["즐겜"],
                status="waiting",
            )
        )
    db.commit()
    barrier = Barrier(2)

    def attempt() -> int | None:
        with session_factory() as worker_db:
            barrier.wait()
            match = try_form_match(worker_db)
            return match.id if match else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    assert sum(result is not None for result in results) == 1
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Match)) == 1
    assert db.scalar(select(func.count()).select_from(MatchMember)) == 5
