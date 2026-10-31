from __future__ import annotations

import os

# Tests must not depend on a developer's .env file. Set this before importing
# the app so Settings picks it up (environment wins over .env).
os.environ.setdefault("SECRET_KEY", "test-only-" + "a" * 64)

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
import pyotp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import (  # noqa: E402
    Base,
    configure_sqlite_engine,
    get_db,
    install_guards,
)
from app.main import app  # noqa: E402
from app.realtime import hub as auction_hub  # noqa: E402
from app.routers.auctions import create_limiter  # noqa: E402
from app.routers.auth import (  # noqa: E402
    login_account_limiter,
    login_ip_limiter,
    mfa_limiter,
    register_limiter,
)
from app.routers.bids import bid_limiter  # noqa: E402

PASSWORD = "Str0ng-Passphrase-42"
COOKIE = "__Host-ra_session"

_LIMITERS = (
    login_ip_limiter,
    login_account_limiter,
    register_limiter,
    mfa_limiter,
    create_limiter,
    bid_limiter,
)


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """In-memory database with production pragmas, tables, and triggers."""
    bind = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_sqlite_engine(bind)
    Base.metadata.create_all(bind=bind)
    install_guards(bind)

    yield bind

    Base.metadata.drop_all(bind=bind)
    bind.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Factory for direct database access inside a test.

    Used to set up state the API cannot reach — for example, backdating an
    auction so it looks expired.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session bound to the same database the client uses."""
    with session_factory() as session:
        yield session


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """Test client wired to the isolated database.

    ``https`` base URL so ``Secure``/``__Host-`` cookies are stored, and the
    in-memory limiters are cleared so tests cannot leak budget into each other.
    """

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    for limiter in _LIMITERS:
        limiter.clear()
    # The hub is a process singleton; do not leak sockets between tests.
    auction_hub.reset()

    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client

    auction_hub.reset()
    app.dependency_overrides.clear()


def register(
    client: TestClient,
    *,
    email: str = "buyer@example.com",
    password: str = PASSWORD,
    role: str = "buyer",
):
    """Register and start a session, returning the raw response."""
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "role": role},
    )


def csrf_headers(client: TestClient) -> dict[str, str]:
    """Read the session-bound CSRF token from /auth/me and wrap it in a header."""
    token = client.get("/api/auth/me").json()["csrf_token"]
    return {"X-CSRF-Token": token}


def enable_mfa(client: TestClient, *, password: str = PASSWORD) -> str:
    """Enrol TOTP for the current session and return the shared secret."""
    headers = csrf_headers(client)
    setup = client.post(
        "/api/auth/mfa/setup", json={"password": password}, headers=headers
    )
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]

    code = pyotp.TOTP(secret).now()
    verify = client.post(
        "/api/auth/mfa/verify",
        json={"password": password, "code": code},
        headers=headers,
    )
    assert verify.status_code == 200, verify.text
    return secret


def csrf_of(response) -> str:
    return response.json()["csrf_token"]
