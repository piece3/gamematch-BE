from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.lol_profile import LolProfile
from app.models.match import Match, MatchMember
from app.models.queue_entry import QueueEntry
from app.models.user_match_record import UserMatchRecord
from app.services.match_results import sync_match_result_from_riot

ROLES = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]


def test_join_queue_accepts_howling_abyss(
    client: TestClient,
    user_factory,
    auth_headers,
) -> None:
    user = user_factory(with_profile=True)
    response = client.post(
        "/match/queue/join",
        json={"game_mode": "Howling Abyss"},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    assert response.json()["game_mode"] == "Howling Abyss"


def test_different_game_modes_do_not_match_together(
    client: TestClient,
    db: Session,
    user_factory,
    auth_headers,
) -> None:
    solo_users = [
        user_factory(with_profile=True, position=role) for role in ("TOP", "MID")
    ]
    flex_users = [user_factory(with_profile=True, position=role) for role in ROLES[:4]]

    for user in solo_users:
        assert (
            client.post(
                "/match/queue/join",
                json={"game_mode": "SOLO"},
                headers=auth_headers(user),
            ).status_code
            == 201
        )
    for user in flex_users:
        assert (
            client.post(
                "/match/queue/join",
                json={"game_mode": "FLEX"},
                headers=auth_headers(user),
            ).status_code
            == 201
        )

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Match)) == 1
    match = db.scalar(select(Match))
    assert match is not None
    assert match.game_mode == "SOLO"
    assert (
        db.scalar(
            select(func.count())
            .select_from(MatchMember)
            .where(MatchMember.match_id == match.id)
        )
        == 2
    )
    waiting_flex = db.scalar(
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.game_mode == "FLEX", QueueEntry.status == "waiting")
    )
    assert waiting_flex == 4


def test_sync_records_win_for_overlapping_team_and_trims_to_five(
    db: Session,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = [user_factory(with_profile=True, position=role) for role in ROLES]
    for index, user in enumerate(users):
        profile = db.scalar(
            select(LolProfile).where(LolProfile.user_id == user.id)
        )
        assert profile is not None
        profile.puuid = f"puuid-{index}"
    now = datetime.now(UTC)
    match = Match(
        game="lol",
        game_mode="SOLO",
        status="completed",
        confirmed_at=now - timedelta(hours=1),
        completed_at=now,
        result_status="pending",
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

    monkeypatch.setattr(
        "app.services.match_results.fetch_recent_match_ids",
        lambda *args, **kwargs: ["KR_1"],
    )
    monkeypatch.setattr(
        "app.services.match_results.fetch_match_detail",
        lambda _match_id: {
            "info": {
                "gameStartTimestamp": int(now.timestamp() * 1000),
                "queueId": 420,
                "participants": [
                    {"puuid": f"puuid-{i}", "teamId": 100, "win": True}
                    for i in range(5)
                ]
                + [
                    {"puuid": f"enemy-{i}", "teamId": 200, "win": False}
                    for i in range(5)
                ],
            }
        },
    )

    assert sync_match_result_from_riot(db, match, preferred_user_id=users[0].id)
    db.commit()

    records = db.scalars(select(UserMatchRecord)).all()
    assert len(records) == 5
    assert all(record.won is True for record in records)
    assert match.result_status == "synced"

    # Add older rows then insert one more via a second sync to enforce the cap.
    for offset in range(5):
        db.add(
            UserMatchRecord(
                user_id=users[0].id,
                match_id=match.id,
                riot_match_id=f"OLD_{offset}",
                game_mode="SOLO",
                won=False,
                played_at=now - timedelta(days=offset + 1),
            )
        )
    db.commit()
    assert (
        db.scalar(
            select(func.count())
            .select_from(UserMatchRecord)
            .where(UserMatchRecord.user_id == users[0].id)
        )
        == 6
    )

    match.result_status = "pending"
    match.riot_match_id = None
    db.commit()
    monkeypatch.setattr(
        "app.services.match_results.fetch_recent_match_ids",
        lambda *args, **kwargs: ["KR_2"],
    )
    monkeypatch.setattr(
        "app.services.match_results.fetch_match_detail",
        lambda _match_id: {
            "info": {
                "gameStartTimestamp": int(now.timestamp() * 1000),
                "queueId": 420,
                "participants": [
                    {"puuid": f"puuid-{i}", "teamId": 100, "win": False}
                    for i in range(5)
                ]
                + [
                    {"puuid": f"enemy-{i}", "teamId": 200, "win": True}
                    for i in range(5)
                ],
            }
        },
    )
    assert sync_match_result_from_riot(db, match, preferred_user_id=users[0].id)
    db.commit()

    user0_count = db.scalar(
        select(func.count())
        .select_from(UserMatchRecord)
        .where(UserMatchRecord.user_id == users[0].id)
    )
    assert user0_count == 5
