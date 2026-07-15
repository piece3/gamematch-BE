from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import create_access_token
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.services.email_verification import create_and_store_verification_token


def test_register_is_generic_and_resend_is_rate_limited(
    client: TestClient,
    db: Session,
) -> None:
    payload = {
        "email": "new-user@jnu.ac.kr",
        "nickname": "new-user",
        "password": "Password1!",
        "college": "Engineering",
        "department": "Computer",
    }

    first = client.post("/auth/register", json=payload)
    second = client.post("/auth/register", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()
    user = db.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    token_count = db.scalar(
        select(func.count())
        .select_from(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id)
    )
    assert token_count == 1


def test_malformed_subject_returns_401(client: TestClient) -> None:
    token = create_access_token("not-an-integer")

    response = client.get(
        "/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_unverified_user_cannot_use_protected_api(
    client: TestClient,
    user_factory,
    auth_headers,
) -> None:
    user = user_factory(verified=False)

    response = client.get("/profile/me", headers=auth_headers(user))

    assert response.status_code == 403


def test_concurrent_resends_create_only_one_valid_token(
    db: Session,
    user_factory,
    session_factory: sessionmaker[Session],
) -> None:
    user = user_factory(verified=False)
    barrier = Barrier(2)

    def issue_token() -> str | None:
        with session_factory() as worker_db:
            worker_user = worker_db.get(User, user.id)
            assert worker_user is not None
            barrier.wait()
            return create_and_store_verification_token(
                worker_db,
                worker_user,
                respect_cooldown=True,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: issue_token(), range(2)))

    assert sum(token is not None for token in results) == 1
    db.expire_all()
    token_count = db.scalar(
        select(func.count())
        .select_from(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
    )
    assert token_count == 1
