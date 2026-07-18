from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.fc_online_match_record import FcOnlineMatchRecord
from app.models.fc_online_profile import FcOnlineProfile
from app.models.match import Match, MatchMember
from app.services.fc_online import (
    DivisionValue,
    FcOnlineApiError,
    FcOnlineSyncPayload,
    build_sync_payload,
)
from app.services.match_results import sync_match_result_from_fc_online


def _add_fc_profile(
    db: Session,
    user_id: int,
    *,
    ouid: str,
    rank_1v1: int = 3,
    rank_2v2: int = 4,
) -> FcOnlineProfile:
    profile = FcOnlineProfile(
        user_id=user_id,
        nickname=f"fc-{user_id}",
        ouid=ouid,
        level=100,
        division_1v1_id=rank_1v1,
        division_1v1_name=f"1v1-{rank_1v1}",
        division_1v1_rank=rank_1v1,
        division_2v2_id=rank_2v2,
        division_2v2_name=f"2v2-{rank_2v2}",
        division_2v2_rank=rank_2v2,
        synced_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    db.add(profile)
    db.commit()
    return profile


def test_build_sync_payload_maps_1v1_and_2v2_divisions() -> None:
    payload = build_sync_payload(
        ouid="ouid-1",
        basic={"nickname": "구단주", "level": 123},
        max_divisions=[
            {"matchType": 50, "division": 10},
            {"matchType": 52, "division": 20},
        ],
        division_metadata=[(10, "월드클래스"), (20, "챌린저")],
    )

    assert payload.nickname == "구단주"
    assert payload.division_1v1.division_name == "월드클래스"
    assert payload.division_1v1.division_rank == 1
    assert payload.division_2v2.division_name == "챌린저"
    assert payload.division_2v2.division_rank == 2


def test_sync_profile_and_api_error_mapping(
    client: TestClient,
    user_factory,
    auth_headers,
    monkeypatch,
) -> None:
    user = user_factory()
    sync_payload = FcOnlineSyncPayload(
        nickname="구단주",
        ouid="ouid-profile",
        level=50,
        division_1v1=DivisionValue(10, "월드클래스", 3),
        division_2v2=DivisionValue(20, "프로", 5),
    )
    monkeypatch.setattr("app.api.fc_online.fetch_ouid", lambda _: "ouid-profile")
    monkeypatch.setattr(
        "app.api.fc_online.fetch_sync_payload_for_ouid",
        lambda _: sync_payload,
    )

    response = client.post(
        "/profile/fc-online/sync",
        json={"nickname": "구단주"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    assert response.json()["division_1v1_name"] == "월드클래스"

    monkeypatch.setattr(
        "app.api.fc_online.fetch_ouid",
        lambda _: (_ for _ in ()).throw(
            FcOnlineApiError("FC Online account was not found.", status_code=404)
        ),
    )
    missing = client.post(
        "/profile/fc-online/sync",
        json={"nickname": "없는구단주"},
        headers=auth_headers(user_factory()),
    )
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(429, 429), (503, 503)],
)
def test_fc_api_transient_error_mapping(
    client: TestClient,
    user_factory,
    auth_headers,
    monkeypatch,
    upstream_status: int,
    expected_status: int,
) -> None:
    user = user_factory()

    def fail(_: str) -> str:
        raise FcOnlineApiError("FC Online API unavailable.", upstream_status)

    monkeypatch.setattr("app.api.fc_online.fetch_ouid", fail)
    response = client.post(
        "/profile/fc-online/sync",
        json={"nickname": "구단주"},
        headers=auth_headers(user),
    )
    assert response.status_code == expected_status


def test_fc_1v1_and_external_party_2v2_matchmaking(
    client: TestClient,
    db: Session,
    user_factory,
    auth_headers,
) -> None:
    one_v_one = [user_factory() for _ in range(2)]
    for index, user in enumerate(one_v_one):
        _add_fc_profile(db, user.id, ouid=f"one-{index}")
        response = client.post(
            "/match/queue/join",
            json={
                "game": "fc_online",
                "game_mode": "OFFICIAL_1V1",
                "party_size": 1,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201

    match_1v1 = db.scalar(
        select(Match).where(Match.game_mode == "OFFICIAL_1V1")
    )
    assert match_1v1 is not None
    assert match_1v1.party_size == 1
    assert (
        db.scalar(
            select(func.count())
            .select_from(MatchMember)
            .where(MatchMember.match_id == match_1v1.id)
        )
        == 2
    )

    for user in one_v_one:
        accepted = client.post(
            f"/match/{match_1v1.id}/accept",
            headers=auth_headers(user),
        )
        assert accepted.status_code == 200
    assert accepted.json()["status"] == "confirmed"

    two_v_two = [user_factory() for _ in range(2)]
    for index, user in enumerate(two_v_two):
        _add_fc_profile(db, user.id, ouid=f"two-{index}")
        response = client.post(
            "/match/queue/join",
            json={
                "game": "fc_online",
                "game_mode": "OFFICIAL_2V2",
                "party_size": 2,
            },
            headers=auth_headers(user),
        )
        assert response.status_code == 201
    db.expire_all()
    match_2v2 = db.scalar(
        select(Match).where(Match.game_mode == "OFFICIAL_2V2")
    )
    assert match_2v2 is not None
    assert match_2v2.party_size == 2

    invalid = client.post(
        "/match/queue/join",
        json={
            "game": "fc_online",
            "game_mode": "OFFICIAL_2V2",
            "party_size": 1,
        },
        headers=auth_headers(user_factory()),
    )
    assert invalid.status_code == 422


def test_fc_result_sync_requires_common_match_and_keeps_five(
    db: Session,
    user_factory,
    monkeypatch,
) -> None:
    users = [user_factory() for _ in range(2)]
    for index, user in enumerate(users):
        _add_fc_profile(db, user.id, ouid=f"result-{index}")

    now = datetime.now(UTC)
    match = Match(
        game="fc_online",
        game_mode="OFFICIAL_1V1",
        party_size=1,
        status="completed",
        result_status="unresolved",
        confirmed_at=now - timedelta(minutes=10),
        completed_at=now,
    )
    db.add(match)
    db.flush()
    for index, user in enumerate(users, start=1):
        db.add(
            MatchMember(
                match_id=match.id,
                user_id=user.id,
                tier="월드클래스",
                tier_rank=3,
                position="ANYTHING",
                assigned_role=f"PLAYER_{index}",
                accept_status="accepted",
            )
        )
    for number in range(5):
        db.add(
            FcOnlineMatchRecord(
                user_id=users[0].id,
                match_id=match.id,
                nexon_match_id=f"old-{number}",
                game_mode="OFFICIAL_1V1",
                result="WIN",
                played_at=now - timedelta(days=number + 1),
            )
        )
    db.commit()

    monkeypatch.setattr(
        "app.services.match_results.fetch_fc_recent_match_ids",
        lambda *args, **kwargs: ["common-match"],
    )
    monkeypatch.setattr(
        "app.services.match_results.fetch_fc_match_detail",
        lambda _: {
            "matchType": 50,
            "matchDate": now.isoformat(),
            "matchInfo": [
                {"ouid": "result-0", "matchDetail": {"matchResult": "승"}},
                {"ouid": "result-1", "matchDetail": {"matchResult": "패"}},
            ],
        },
    )

    assert sync_match_result_from_fc_online(db, match)
    db.commit()
    assert match.nexon_match_id == "common-match"
    assert match.result_status == "synced"
    assert (
        db.scalar(
            select(func.count())
            .select_from(FcOnlineMatchRecord)
            .where(FcOnlineMatchRecord.user_id == users[0].id)
        )
        == 5
    )
    results = db.scalars(
        select(FcOnlineMatchRecord.result)
        .where(FcOnlineMatchRecord.nexon_match_id == "common-match")
        .order_by(FcOnlineMatchRecord.user_id)
    ).all()
    assert results == ["WIN", "LOSS"]
