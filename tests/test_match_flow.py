from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.match import Match
from app.models.queue_entry import QueueEntry
from app.models.user import User

ROLES = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]


def _create_and_match_five(client, user_factory, auth_headers):
    users = [
        user_factory(with_profile=True, position=role)
        for role in ROLES
    ]
    for user in users:
        response = client.post(
            "/match/queue/join",
            headers=auth_headers(user),
        )
        assert response.status_code == 201

    active = client.get(
        "/match/active",
        headers=auth_headers(users[0]),
    )
    assert active.status_code == 200
    assert active.json()["status"] == "pending_accept"
    status_response = client.get(
        "/match/queue/status",
        headers=auth_headers(users[0]),
    )
    assert status_response.status_code == 200
    assert status_response.json()["in_queue"] is False
    assert status_response.json()["match_id"] == active.json()["id"]
    duplicate_join = client.post(
        "/match/queue/join",
        headers=auth_headers(users[0]),
    )
    assert duplicate_join.status_code == 409
    return users, active.json()["id"]


def test_queue_accept_complete_evaluate_and_history(
    client: TestClient,
    db: Session,
    user_factory,
    auth_headers,
) -> None:
    users, match_id = _create_and_match_five(
        client,
        user_factory,
        auth_headers,
    )

    for user in users:
        accepted = client.post(
            f"/match/{match_id}/accept",
            headers=auth_headers(user),
        )
        assert accepted.status_code == 200
    assert accepted.json()["status"] == "confirmed"

    completed = client.post(
        f"/match/{match_id}/complete",
        headers=auth_headers(users[0]),
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    evaluation = client.post(
        f"/match/{match_id}/evaluate",
        headers=auth_headers(users[0]),
        json={
            "evaluations": [
                {"target_user_id": user.id, "manner_delta": 1}
                for user in users[1:]
            ]
        },
    )
    assert evaluation.status_code == 200

    history = client.get(
        "/match/history",
        headers=auth_headers(users[0]),
    )
    assert history.status_code == 200
    assert history.json()["items"][0]["evaluation_submitted"] is True

    db.expire_all()
    targets = db.scalars(
        select(User).where(User.id.in_([user.id for user in users[1:]]))
    ).all()
    assert all(target.manner_score == 3.2 for target in targets)


def test_decliner_is_removed_and_other_members_are_requeued(
    client: TestClient,
    db: Session,
    user_factory,
    auth_headers,
) -> None:
    users, match_id = _create_and_match_five(
        client,
        user_factory,
        auth_headers,
    )

    response = client.post(
        f"/match/{match_id}/decline",
        headers=auth_headers(users[0]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    db.expire_all()
    match = db.get(Match, match_id)
    assert match is not None and match.status == "cancelled"
    assert db.scalar(
        select(QueueEntry).where(QueueEntry.user_id == users[0].id)
    ) is None
    waiting_count = db.scalar(
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.status == "waiting")
    )
    assert waiting_count == 4
