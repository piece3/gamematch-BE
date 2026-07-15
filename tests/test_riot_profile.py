import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lol_profile import LolProfile
from app.models.queue_entry import QueueEntry
from app.services import riot
from app.services.riot import RiotApiError, RiotRankResult


def test_riot_sync_stores_full_rank_and_enforces_cooldown(
    client: TestClient,
    db: Session,
    user_factory,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory(with_profile=True)
    db.add(
        QueueEntry(
            user_id=user.id,
            game="lol",
            tier="SILVER",
            tier_rank=3,
            position="ANYTHING",
            secondary_position="ANYTHING",
            status="waiting",
        )
    )
    db.commit()
    monkeypatch.setattr(
        "app.api.profile.fetch_rank_by_riot_id",
        lambda _: RiotRankResult(
            riot_id="Player#KR1",
            puuid="puuid-1",
            tier="GOLD",
            rank_division="II",
            league_points=73,
        ),
    )
    monkeypatch.setattr(
        "app.api.profile.verify_riot_account_ownership",
        lambda _puuid, _code: True,
    )

    first = client.post(
        "/profile/riot/sync",
        json={
            "riot_id": "Player#KR1",
            "verification_code": "owned",
        },
        headers=auth_headers(user),
    )
    second = client.post(
        "/profile/riot/sync",
        json={
            "riot_id": "Player#KR1",
            "verification_code": "owned",
        },
        headers=auth_headers(user),
    )

    assert first.status_code == 200
    assert first.json()["lol_profile"]["rank_division"] == "II"
    assert first.json()["lol_profile"]["league_points"] == 73
    assert second.status_code == 429
    profile = db.scalar(select(LolProfile).where(LolProfile.user_id == user.id))
    assert profile is not None
    assert profile.puuid == "puuid-1"
    queue_entry = db.scalar(
        select(QueueEntry).where(QueueEntry.user_id == user.id)
    )
    assert queue_entry is not None
    assert (queue_entry.tier, queue_entry.tier_rank) == ("GOLD", 4)


def test_same_riot_account_cannot_be_linked_twice(
    client: TestClient,
    user_factory,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_user = user_factory(with_profile=True)
    second_user = user_factory(with_profile=True)
    monkeypatch.setattr(
        "app.api.profile.fetch_rank_by_riot_id",
        lambda riot_id: RiotRankResult(
            riot_id=riot_id,
            puuid="shared-puuid",
            tier="SILVER",
            rank_division="I",
            league_points=10,
        ),
    )
    monkeypatch.setattr(
        "app.api.profile.verify_riot_account_ownership",
        lambda _puuid, _code: True,
    )

    first = client.post(
        "/profile/riot/sync",
        json={"riot_id": "One#KR1", "verification_code": "owned"},
        headers=auth_headers(first_user),
    )
    second = client.post(
        "/profile/riot/sync",
        json={"riot_id": "Two#KR1", "verification_code": "owned"},
        headers=auth_headers(second_user),
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_new_riot_link_requires_matching_ownership_code(
    client: TestClient,
    user_factory,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory(with_profile=True)
    monkeypatch.setattr(
        "app.api.profile.fetch_rank_by_riot_id",
        lambda _: RiotRankResult(
            riot_id="Player#KR1",
            puuid="protected-puuid",
            tier="SILVER",
        ),
    )
    monkeypatch.setattr(
        "app.api.profile.verify_riot_account_ownership",
        lambda _puuid, _code: False,
    )

    response = client.post(
        "/profile/riot/sync",
        json={
            "riot_id": "Player#KR1",
            "verification_code": "wrong",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 403


def test_riot_client_maps_full_rank(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/riot/account/" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "puuid": "riot-puuid",
                    "gameName": "Player",
                    "tagLine": "KR1",
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "queueType": "RANKED_SOLO_5x5",
                    "tier": "PLATINUM",
                    "rank": "III",
                    "leaguePoints": 44,
                }
            ],
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(riot, "_client", mock_client)

    result = riot.fetch_rank_by_riot_id("Player#KR1")

    assert (result.tier, result.rank_division, result.league_points) == (
        "PLATINUM",
        "III",
        44,
    )
    mock_client.close()


def test_riot_ownership_code_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/summoner/v4/" in str(request.url):
            return httpx.Response(200, json={"id": "summoner-id"})
        return httpx.Response(200, json="client-code")

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(riot, "_client", mock_client)

    assert riot.verify_riot_account_ownership("puuid", "client-code")
    assert not riot.verify_riot_account_ownership("puuid", "wrong-code")
    mock_client.close()


@pytest.mark.parametrize("status_code", [403, 404, 429])
def test_riot_client_preserves_error_status(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"Retry-After": "5"} if status_code == 429 else {}
    mock_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status_code, headers=headers)
        )
    )
    monkeypatch.setattr(riot, "_client", mock_client)

    with pytest.raises(RiotApiError) as error:
        riot.fetch_account_by_riot_id("Player#KR1")

    assert error.value.status_code == status_code
    if status_code == 429:
        assert error.value.retry_after == 5
    mock_client.close()
