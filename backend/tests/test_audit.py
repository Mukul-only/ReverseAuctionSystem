"""Audit ledger tests.

Covers event recording for core actions, chain verification, tamper and
truncation detection, security-event filtering, and the signed anchor.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditEvent
from app.services import audit_service
from conftest import csrf_headers, register

BUYER = "audit-buyer@example.com"
SELLER = "audit-seller@example.com"

START = 1_000_000
DECREMENT = 5_000


def sign_in(client: TestClient, email: str, role: str) -> dict[str, str]:
    client.cookies.clear()
    register(client, email=email, role=role)
    return csrf_headers(client)


def create_auction(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/auctions",
        json={
            "title": "Audited auction",
            "description": "audit",
            "starting_price": START,
            "min_decrement": DECREMENT,
            "duration_hours": 48,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def drop_immutability_guards(session_factory: sessionmaker[Session]) -> None:
    """Remove the append-only triggers so a test can simulate a DB attacker."""
    with session_factory() as session:
        session.execute(text("DROP TRIGGER IF EXISTS audit_events_no_update"))
        session.execute(text("DROP TRIGGER IF EXISTS audit_events_no_delete"))
        session.commit()


def recorded_actions(
    session_factory: sessionmaker[Session], **kwargs: object
) -> list[str]:
    with session_factory() as session:
        return [
            event.action
            for event in audit_service.list_events(session, limit=100, **kwargs)  # type: ignore[arg-type]
        ]


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def test_core_actions_are_recorded(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = sign_in(client, BUYER, "buyer")
    auction_id = create_auction(client, headers)

    seller_headers = sign_in(client, SELLER, "seller")
    response = client.post(
        f"/api/auctions/{auction_id}/bids",
        json={"amount": START - DECREMENT, "idempotency_key": "audit-key-1"},
        headers=seller_headers,
    )
    assert response.status_code == 201

    actions = set(recorded_actions(session_factory))
    assert {"auth.register", "auction.created", "bid.placed"} <= actions


def test_failed_login_is_recorded(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    sign_in(client, BUYER, "buyer")
    client.cookies.clear()

    client.post(
        "/api/auth/login", json={"email": BUYER, "password": "Wrong-Password-1"}
    )

    assert "auth.login_failed" in recorded_actions(session_factory)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def test_chain_verifies_after_activity(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = sign_in(client, BUYER, "buyer")
    create_auction(client, headers)

    with session_factory() as session:
        report = audit_service.verify(session)

    assert report["valid"] is True
    assert report["checked"] == report["event_count"]
    assert report["head_hash"]


def test_chain_detects_an_altered_event(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = sign_in(client, BUYER, "buyer")
    create_auction(client, headers)
    drop_immutability_guards(session_factory)

    with session_factory() as session:
        victim = session.query(AuditEvent).order_by(AuditEvent.seq.asc()).first()
        assert victim is not None
        victim.metadata_json = '{"tampered":true}'
        session.commit()

    with session_factory() as session:
        report = audit_service.verify(session)

    assert report["valid"] is False
    assert report["reason"] is not None


def test_chain_detects_a_removed_event(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = sign_in(client, BUYER, "buyer")
    create_auction(client, headers)
    create_auction(client, headers)
    drop_immutability_guards(session_factory)

    with session_factory() as session:
        rows = session.query(AuditEvent).order_by(AuditEvent.seq.asc()).all()
        assert len(rows) >= 3
        session.delete(rows[1])
        session.commit()

    with session_factory() as session:
        report = audit_service.verify(session)

    assert report["valid"] is False
    assert "removed or reordered" in str(report["reason"])


def test_anchor_signs_the_head(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = sign_in(client, BUYER, "buyer")
    create_auction(client, headers)

    with session_factory() as session:
        anchor = audit_service.anchor(session)
        assert anchor["seq"] is not None
        assert anchor["signature"]
        assert audit_service.verify_anchor(
            session,
            seq=anchor["seq"],
            hash_=anchor["hash"],
            count=anchor["event_count"],
            signature=anchor["signature"],
        )
        # A truncated ledger no longer matches the anchor.
        assert not audit_service.verify_anchor(
            session,
            seq=anchor["seq"],
            hash_=anchor["hash"],
            count=anchor["event_count"] - 1,
            signature=anchor["signature"],
        )


def test_security_event_filter(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = sign_in(client, BUYER, "buyer")
    create_auction(client, headers)

    with session_factory() as session:
        security = audit_service.list_events(session, security_only=True, limit=50)

    assert security
    assert all(event.action in audit_service.SECURITY_ACTIONS for event in security)