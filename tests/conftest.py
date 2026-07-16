import os
from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://gamematch:gamematch@localhost:5432/gamematch_test",
)
database_name = make_url(TEST_DATABASE_URL).database or ""
if "test" not in database_name.lower():
    raise RuntimeError("Tests require a database whose name contains 'test'")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["EMAIL_DEV_MODE"] = "true"
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters")
os.environ.setdefault("RIOT_API_KEY", "test-riot-key")

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.lol_profile import LolProfile  # noqa: E402
from app.models.user import User  # noqa: E402

test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE "
                "user_match_records, match_evaluations, match_members, matches, "
                "queue_entries, lol_profiles, email_verification_tokens, users "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def session_factory():
    return TestingSessionLocal


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user_factory(db: Session) -> Callable[..., User]:
    sequence = 0

    def create_user(
        *,
        email: str | None = None,
        nickname: str | None = None,
        verified: bool = True,
        with_profile: bool = False,
        position: str = "ANYTHING",
    ) -> User:
        nonlocal sequence
        sequence += 1
        user = User(
            email=email or f"user{sequence}@jnu.ac.kr",
            nickname=nickname or f"user{sequence}",
            hashed_password=hash_password("Password1!"),
            is_verified=verified,
            college="Engineering",
            department="Computer",
        )
        db.add(user)
        db.flush()
        if with_profile:
            db.add(
                LolProfile(
                    user_id=user.id,
                    tier="SILVER",
                    tier_rank=3,
                    primary_position=position,
                    secondary_position="ANYTHING",
                    play_styles=["즐겜"],
                )
            )
        db.commit()
        db.refresh(user)
        return user

    return create_user


@pytest.fixture
def auth_headers() -> Callable[[User], dict[str, str]]:
    def headers(user: User) -> dict[str, str]:
        token = create_access_token(str(user.id))
        return {"Authorization": f"Bearer {token}"}

    return headers
