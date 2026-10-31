"""TOTP second-factor tests.

Covers enrolment, the login challenge flow, replay protection, disable, secret
encryption at rest, CSRF gates, and admin enforcement.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import pyotp
from app.models import Role, User
from app.services import auth_service
from conftest import PASSWORD, csrf_headers, enable_mfa, register

EMAIL = "mfa@example.com"
ADMIN = "mfa-admin@example.com"


def sign_in(client: TestClient, email: str = EMAIL) -> None:
    client.cookies.clear()
    register(client, email=email)


def setup(client: TestClient, password: str = PASSWORD):
    return client.post(
        "/api/auth/mfa/setup",
        json={"password": password},
        headers=csrf_headers(client),
    )


# --------------------------------------------------------------------------
# Enrolment
# --------------------------------------------------------------------------


def test_setup_returns_a_provisioning_uri(client: TestClient) -> None:
    sign_in(client)

    response = setup(client)

    assert response.status_code == 200
    body = response.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "Reverse%20Auctions" in body["otpauth_uri"]
    assert len(body["secret"]) >= 16


def test_confirm_enables_the_second_factor(client: TestClient) -> None:
    sign_in(client)
    secret = setup(client).json()["secret"]

    response = client.post(
        "/api/auth/mfa/verify",
        json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["user"]["totp_enabled"] is True


def test_confirm_rejects_a_wrong_code(client: TestClient) -> None:
    sign_in(client)
    setup(client)

    response = client.post(
        "/api/auth/mfa/verify",
        json={"password": PASSWORD, "code": "000000"},
        headers=csrf_headers(client),
    )

    assert response.status_code == 409
    assert client.get("/api/auth/me").json()["user"]["totp_enabled"] is False


def test_setup_requires_the_correct_password(client: TestClient) -> None:
    sign_in(client)

    response = setup(client, password="Not-The-Password-9")

    assert response.status_code == 403


def test_setup_requires_csrf(client: TestClient) -> None:
    sign_in(client)

    response = client.post(
        "/api/auth/mfa/setup", json={"password": PASSWORD}
    )

    assert response.status_code == 403


def test_enrolment_is_not_repeatable(client: TestClient) -> None:
    sign_in(client)
    enable_mfa(client)

    response = setup(client)

    assert response.status_code == 409


def test_secret_is_encrypted_at_rest(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    sign_in(client)
    secret = enable_mfa(client)

    with session_factory() as session:
        user = session.query(User).filter_by(email=EMAIL).one()
        assert user.totp_secret_enc is not None
        assert secret not in user.totp_secret_enc


# --------------------------------------------------------------------------
# Login challenge
# --------------------------------------------------------------------------


def test_login_prompts_for_a_second_factor(client: TestClient) -> None:
    sign_in(client)
    enable_mfa(client)
    client.cookies.clear()

    response = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is True
    assert body["user"] is None
    assert body["challenge"]
    # No session cookie is handed out before the second factor.
    assert "set-cookie" not in response.headers


def test_mfa_login_completes_with_a_valid_code(client: TestClient) -> None:
    sign_in(client)
    secret = enable_mfa(client)
    client.cookies.clear()

    challenge = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["challenge"]

    response = client.post(
        "/api/auth/mfa/login",
        json={"challenge": challenge, "code": pyotp.TOTP(secret).now()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is False
    assert body["user"]["email"] == EMAIL
    assert "set-cookie" in response.headers


def test_mfa_login_rejects_a_wrong_code(client: TestClient) -> None:
    sign_in(client)
    enable_mfa(client)
    client.cookies.clear()
    challenge = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["challenge"]

    response = client.post(
        "/api/auth/mfa/login", json={"challenge": challenge, "code": "111111"}
    )

    assert response.status_code == 401


def test_mfa_login_rejects_a_forged_challenge(client: TestClient) -> None:
    sign_in(client)
    secret = enable_mfa(client)
    client.cookies.clear()

    response = client.post(
        "/api/auth/mfa/login",
        json={"challenge": "forged.challenge.value", "code": pyotp.TOTP(secret).now()},
    )

    assert response.status_code == 401


def test_mfa_login_rejects_a_replayed_code(client: TestClient) -> None:
    sign_in(client)
    secret = enable_mfa(client)
    client.cookies.clear()

    def challenge() -> str:
        return client.post(
            "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
        ).json()["challenge"]

    code = pyotp.TOTP(secret).now()
    first = client.post(
        "/api/auth/mfa/login", json={"challenge": challenge(), "code": code}
    )
    assert first.status_code == 200

    replay = client.post(
        "/api/auth/mfa/login", json={"challenge": challenge(), "code": code}
    )
    assert replay.status_code == 401


# --------------------------------------------------------------------------
# Disable
# --------------------------------------------------------------------------


def test_disable_removes_the_factor(client: TestClient) -> None:
    sign_in(client)
    secret = enable_mfa(client)

    response = client.post(
        "/api/auth/mfa/disable",
        json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["user"]["totp_enabled"] is False


def test_disable_requires_a_valid_code(client: TestClient) -> None:
    sign_in(client)
    enable_mfa(client)

    response = client.post(
        "/api/auth/mfa/disable",
        json={"password": PASSWORD, "code": "000000"},
        headers=csrf_headers(client),
    )

    assert response.status_code == 409


# --------------------------------------------------------------------------
# Admin enforcement
# --------------------------------------------------------------------------


def test_admin_routes_require_enrolled_mfa(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        auth_service.register_user(
            session, email=ADMIN, password=PASSWORD, role=Role.ADMIN
        )
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": ADMIN, "password": PASSWORD})

    blocked = client.get("/api/admin/users")
    assert blocked.status_code == 403

    enable_mfa(client)
    allowed = client.get("/api/admin/users")
    assert allowed.status_code == 200
