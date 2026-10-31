from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, configure_sqlite_engine, get_db, install_guards
from app.main import app
from app.routers.auth import (
    login_account_limiter,
    login_ip_limiter,
    register_limiter,
)

PASSWORD = "Str0ng-Passphrase-42"
COOKIE = "__Host-ra_session"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_sqlite_engine(engine)
    Base.metadata.create_all(bind=engine)
    install_guards(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    login_ip_limiter.clear()
    login_account_limiter.clear()
    register_limiter.clear()

    # https so Secure/__Host- cookies are actually stored and replayed.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register(
    client: TestClient,
    *,
    email: str = "buyer@example.com",
    password: str = PASSWORD,
    role: str = "buyer",
):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "role": role},
    )


# --------------------------------------------------------------------------
# Registration and sessions
# --------------------------------------------------------------------------


def test_register_creates_session_and_secure_cookie(client: TestClient) -> None:
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "buyer@example.com"
    assert body["user"]["role"] == "buyer"
    assert len(body["csrf_token"]) >= 32

    cookie = response.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie


def test_me_returns_the_current_user(client: TestClient) -> None:
    register(client)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "buyer@example.com"


def test_me_requires_a_session(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_duplicate_registration_is_generic(client: TestClient) -> None:
    register(client)

    response = register(client, email="BUYER@example.com")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Registration could not be completed with those details."
    )


def test_self_registration_cannot_create_admin(client: TestClient) -> None:
    response = register(client, role="admin")

    assert response.status_code == 422


def test_short_password_is_rejected(client: TestClient) -> None:
    response = register(client, password="short")

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Login, rotation, and logout
# --------------------------------------------------------------------------


def test_login_rejects_wrong_password_with_generic_message(
    client: TestClient,
) -> None:
    register(client)

    response = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": "WrongPassword-99"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_unknown_email_and_wrong_password_look_identical(
    client: TestClient,
) -> None:
    register(client)

    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "WrongPassword-99"},
    )
    wrong = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": "WrongPassword-99"},
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_login_rotates_the_session_token(client: TestClient) -> None:
    first = register(client)
    old_token = client.cookies.get(COOKIE)
    assert old_token

    second = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": PASSWORD},
    )
    new_token = client.cookies.get(COOKIE)

    assert second.status_code == 200
    assert new_token and new_token != old_token
    assert second.json()["csrf_token"] != first.json()["csrf_token"]

    client.cookies.clear()
    client.cookies.set(COOKIE, old_token)
    assert client.get("/api/auth/me").status_code == 401

    client.cookies.clear()
    client.cookies.set(COOKIE, new_token)
    assert client.get("/api/auth/me").status_code == 200


def test_logout_requires_csrf(client: TestClient) -> None:
    register(client)

    response = client.post("/api/auth/logout")

    assert response.status_code == 403


def test_logout_rejects_wrong_csrf(client: TestClient) -> None:
    register(client)

    response = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": "not-the-token"}
    )

    assert response.status_code == 403


def test_logout_revokes_the_session(client: TestClient) -> None:
    registration = register(client)
    csrf = registration.json()["csrf_token"]

    response = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# Abuse controls
# --------------------------------------------------------------------------


def test_account_locks_after_repeated_failures(client: TestClient) -> None:
    register(client)

    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": "buyer@example.com", "password": "WrongPassword-99"},
        )
        assert response.status_code == 401

    # Correct password now fails because the account is locked.
    response = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": PASSWORD},
    )
    assert response.status_code == 401


def test_login_is_rate_limited(client: TestClient) -> None:
    register(client)

    for _ in range(10):
        client.post(
            "/api/auth/login",
            json={"email": "buyer@example.com", "password": "WrongPassword-99"},
        )

    response = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": "WrongPassword-99"},
    )

    assert response.status_code == 429
    assert "retry-after" in response.headers


def test_registration_is_rate_limited(client: TestClient) -> None:
    for index in range(5):
        assert register(client, email=f"user{index}@example.com").status_code == 201

    response = register(client, email="user5@example.com")

    assert response.status_code == 429


# --------------------------------------------------------------------------
# Origin check (login CSRF)
# --------------------------------------------------------------------------


def test_foreign_origin_cannot_post(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Origin not allowed."


def test_trusted_origin_is_allowed(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "buyer@example.com", "password": PASSWORD},
        headers={"Origin": "http://localhost:5173"},
    )

    # Origin passes; the account simply does not exist yet.
    assert response.status_code == 401