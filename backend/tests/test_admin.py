"""Admin console tests: authorization, user administration, and audit views."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Role, User
from app.models.mixins import utcnow
from app.services import admin_service, audit_service, auth_service
from conftest import COOKIE, PASSWORD, csrf_headers, enable_mfa, register

ADMIN = "console-admin@example.com"
BUYER = "console-buyer@example.com"


def make_admin(
    client: TestClient, session_factory: sessionmaker[Session], *, email: str = ADMIN
) -> dict[str, str]:
    with session_factory() as session:
        auth_service.register_user(
            session, email=email, password=PASSWORD, role=Role.ADMIN
        )
    client.cookies.clear()
    login = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    enable_mfa(client)
    return csrf_headers(client)


def make_user(
    client: TestClient, session_factory: sessionmaker[Session], *, email: str = BUYER
) -> int:
    with session_factory() as session:
        user = auth_service.register_user(
            session, email=email, password=PASSWORD, role=Role.BUYER
        )
        return user.id


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


def test_admin_routes_reject_non_admins(client: TestClient) -> None:
    register(client, email=BUYER, role="buyer")

    response = client.get("/api/admin/users")

    assert response.status_code == 403


def test_admin_routes_reject_anonymous(client: TestClient) -> None:
    assert client.get("/api/admin/users").status_code == 401


def test_admin_mutation_requires_csrf(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    make_admin(client, session_factory)
    target = make_user(client, session_factory)

    response = client.patch(f"/api/admin/users/{target}/role", json={"role": "seller"})

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


def test_list_users(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    make_admin(client, session_factory)
    make_user(client, session_factory)

    response = client.get("/api/admin/users")

    assert response.status_code == 200
    emails = {user["email"] for user in response.json()}
    assert {ADMIN, BUYER} <= emails


def test_change_role(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = make_admin(client, session_factory)
    target = make_user(client, session_factory)

    response = client.patch(
        f"/api/admin/users/{target}/role", json={"role": "seller"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["role"] == "seller"

    with session_factory() as session:
        actions = [
            event.action for event in audit_service.list_events(session, limit=100)
        ]
    assert "admin.role_changed" in actions


def test_admin_cannot_change_their_own_role(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = make_admin(client, session_factory)
    with session_factory() as session:
        admin_id = session.query(User).filter_by(email=ADMIN).one().id

    response = client.patch(
        f"/api/admin/users/{admin_id}/role", json={"role": "buyer"}, headers=headers
    )

    assert response.status_code == 403


def test_last_admin_cannot_be_demoted(
    session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        target = auth_service.register_user(
            session, email="only-admin@example.com", password=PASSWORD, role=Role.ADMIN
        )
        phantom = User(id=9_999, email="phantom@example.com", password_hash="x")
        phantom.role = Role.ADMIN
        try:
            admin_service.change_role(session, phantom, target, Role.BUYER)
        except admin_service.AdminStateError:
            pass
        else:  # pragma: no cover
            raise AssertionError("last admin was demoted")


def test_unlock_clears_a_lockout(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = make_admin(client, session_factory)
    target = make_user(client, session_factory)

    with session_factory() as session:
        user = session.get(User, target)
        assert user is not None
        user.locked_until = utcnow() + timedelta(minutes=10)
        user.failed_attempts = 4
        session.commit()

    response = client.post(f"/api/admin/users/{target}/unlock", headers=headers)

    assert response.status_code == 200
    assert response.json()["locked_until"] is None
    assert response.json()["failed_attempts"] == 0


def test_revoke_sessions_ends_them(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    # Start a buyer session and capture its token.
    register(client, email=BUYER, role="seller")
    buyer_token = client.cookies.get(COOKIE)
    assert buyer_token
    with session_factory() as session:
        buyer_id = session.query(User).filter_by(email=BUYER).one().id

    client.cookies.clear()
    headers = make_admin(client, session_factory)

    response = client.post(
        f"/api/admin/users/{buyer_id}/revoke-sessions", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["revoked"] == 1

    client.cookies.clear()
    client.cookies.set(COOKIE, buyer_token)
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# Audit console
# --------------------------------------------------------------------------


def test_audit_list_and_verify(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = make_admin(client, session_factory)

    listing = client.get("/api/admin/audit")
    assert listing.status_code == 200
    assert listing.json()
    assert isinstance(listing.json()[0]["metadata"], dict)

    verification = client.post("/api/admin/audit/verify", headers=headers)
    assert verification.status_code == 200
    assert verification.json()["valid"] is True


def test_anchor_endpoint(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    make_admin(client, session_factory)

    response = client.get("/api/admin/audit/anchor")

    assert response.status_code == 200
    body = response.json()
    assert body["seq"] is not None
    assert body["signature"]


def test_security_events_endpoint(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    make_admin(client, session_factory)

    response = client.get("/api/admin/security-events")

    assert response.status_code == 200
    assert any(event["action"].startswith(("auth.", "mfa.")) for event in response.json())