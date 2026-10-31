"""Auction lifecycle, ownership, and RBAC tests.

Covers the two guarantees Milestone 4/5 must make:
1. Role gates — only buyers create; sellers and admins are refused.
2. Ownership gates — only the owner may close; owner or admin may cancel.
Plus the IDOR probes, CSRF gate, input validation, and sanitisation.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Auction, AuctionStatus, Role
from app.models.mixins import utcnow
from app.services import auth_service
from conftest import PASSWORD, register

BUYER = "buyer@example.com"
OTHER_BUYER = "buyer2@example.com"
SELLER = "seller@example.com"
ADMIN = "admin@example.com"


def csrf_of(response) -> str:
    return response.json()["csrf_token"]


def signed_in(
    client: TestClient, email: str, role: str
) -> tuple[dict[str, str], str]:
    """Register a user and return (csrf headers, csrf token).

    The helper keeps each test's intent readable: role is explicit and the
    session is always CSRF-ready.
    """
    token = csrf_of(register(client, email=email, role=role))
    return {"X-CSRF-Token": token}, token


def sign_in_admin(
    client: TestClient,
    session_factory: sessionmaker[Session],
    email: str = ADMIN,
) -> tuple[dict[str, str], str]:
    """Admins cannot self-register, so mint one directly then log in."""
    with session_factory() as session:
        auth_service.register_user(
            session, email=email, password=PASSWORD, role=Role.ADMIN
        )

    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    token = csrf_of(response)
    return {"X-CSRF-Token": token}, token


def make_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Bulk chairs",
        "description": "120 units, delivered to campus.",
        "starting_price": 1_000_000,
        "min_decrement": 5_000,
        "duration_hours": 48,
    }
    payload.update(overrides)
    return payload


def create_auction(
    client: TestClient, headers: dict[str, str], **overrides: Any
):
    return client.post("/api/auctions", json=make_payload(**overrides), headers=headers)


# --------------------------------------------------------------------------
# Creation and role enforcement
# --------------------------------------------------------------------------


def test_buyer_can_create_an_auction(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")

    response = create_auction(client, headers)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Bulk chairs"
    assert body["buyer_email"] == BUYER
    assert body["status"] == AuctionStatus.OPEN.value
    assert body["starting_price"] == 1_000_000
    assert body["bid_count"] == 0
    assert body["lowest_bid"] is None


def test_seller_cannot_create_an_auction(client: TestClient) -> None:
    headers, _ = signed_in(client, SELLER, "seller")

    response = create_auction(client, headers)

    assert response.status_code == 403


def test_admin_cannot_create_an_auction(
    client: TestClient, session_factory
) -> None:
    headers, _ = sign_in_admin(client, session_factory)

    response = create_auction(client, headers)

    assert response.status_code == 403


def test_anonymous_cannot_create_an_auction(client: TestClient) -> None:
    response = client.post("/api/auctions", json=make_payload())

    assert response.status_code == 401


def test_create_requires_csrf(client: TestClient) -> None:
    signed_in(client, BUYER, "buyer")

    response = client.post("/api/auctions", json=make_payload())

    assert response.status_code == 403


def test_create_rejects_a_decrement_larger_than_the_start_price(
    client: TestClient,
) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")

    response = create_auction(
        client, headers, starting_price=10_000, min_decrement=20_000
    )

    assert response.status_code == 422


def test_create_rejects_a_short_title(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")

    response = create_auction(client, headers, title="ab")

    assert response.status_code == 422


def test_create_rejects_a_negative_price(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")

    response = create_auction(client, headers, starting_price=-1)

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Reads: list, detail, and the owner-scoped view
# --------------------------------------------------------------------------


def test_listing_is_public_and_returns_open_auctions(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")
    create_auction(client, headers, title="Chairs")
    create_auction(client, headers, title="Laptops")

    response = client.get("/api/auctions")

    assert response.status_code == 200
    titles = {row["title"] for row in response.json()}
    assert titles == {"Chairs", "Laptops"}


def test_detail_returns_404_for_an_unknown_id(client: TestClient) -> None:
    response = client.get("/api/auctions/9999")

    assert response.status_code == 404


def test_mine_is_scoped_to_the_calling_buyer(client: TestClient) -> None:
    first_headers, _ = signed_in(client, BUYER, "buyer")
    create_auction(client, first_headers, title="Mine only")

    # Switch identity: a second buyer must not see the first buyer's rows.
    client.cookies.clear()
    second_headers, _ = signed_in(client, OTHER_BUYER, "buyer")
    create_auction(client, second_headers, title="Not mine")

    response = client.get("/api/auctions/mine")

    assert response.status_code == 200
    body = response.json()
    assert [row["title"] for row in body] == ["Not mine"]
    assert all(row["buyer_email"] == OTHER_BUYER for row in body)


def test_mine_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/auctions/mine")

    assert response.status_code == 401


# --------------------------------------------------------------------------
# Ownership and lifecycle
# --------------------------------------------------------------------------


def backdate(
    session_factory: sessionmaker[Session], auction_id: int, *, minutes: int = 1
) -> None:
    """Push the window into the past so the auction counts as expired."""
    now = utcnow()
    with session_factory() as session:
        auction = session.get(Auction, auction_id)
        assert auction is not None
        # Keep ends_at > starts_at so the window CHECK constraint holds.
        auction.starts_at = now - timedelta(hours=2)
        auction.ends_at = now - timedelta(minutes=minutes)
        session.commit()


def test_only_the_owner_can_close(client: TestClient, session_factory) -> None:
    owner_headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, owner_headers).json()["id"]
    backdate(session_factory, auction_id)

    client.cookies.clear()
    intruder_headers, _ = signed_in(client, OTHER_BUYER, "buyer")
    denied = client.post(
        f"/api/auctions/{auction_id}/close", headers=intruder_headers
    )
    assert denied.status_code == 403


def test_owner_closes_an_expired_auction(
    client: TestClient, session_factory
) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, headers).json()["id"]
    backdate(session_factory, auction_id)

    response = client.post(f"/api/auctions/{auction_id}/close", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == AuctionStatus.CLOSED.value


def test_close_before_the_deadline_is_a_conflict(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, headers).json()["id"]

    response = client.post(f"/api/auctions/{auction_id}/close", headers=headers)

    assert response.status_code == 409


def test_expired_open_auctions_auto_close_on_read(
    client: TestClient, session_factory
) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, headers).json()["id"]
    backdate(session_factory, auction_id)

    # A plain listing read performs the state transition.
    listing = client.get("/api/auctions").json()
    assert all(row["id"] != auction_id for row in listing)

    detail = client.get(f"/api/auctions/{auction_id}")
    assert detail.json()["status"] == AuctionStatus.CLOSED.value


def test_owner_can_cancel(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, headers).json()["id"]

    response = client.post(f"/api/auctions/{auction_id}/cancel", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == AuctionStatus.CANCELLED.value


def test_admin_can_cancel_someone_elses_auction(
    client: TestClient, session_factory
) -> None:
    buyer_headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    client.cookies.clear()
    admin_headers, _ = sign_in_admin(client, session_factory)
    response = client.post(f"/api/auctions/{auction_id}/cancel", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["status"] == AuctionStatus.CANCELLED.value


def test_other_buyer_cannot_cancel(client: TestClient) -> None:
    owner_headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, owner_headers).json()["id"]

    client.cookies.clear()
    intruder_headers, _ = signed_in(client, OTHER_BUYER, "buyer")
    response = client.post(
        f"/api/auctions/{auction_id}/cancel", headers=intruder_headers
    )

    assert response.status_code == 403


def test_seller_cannot_cancel(client: TestClient) -> None:
    buyer_headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    client.cookies.clear()
    seller_headers, _ = signed_in(client, SELLER, "seller")
    response = client.post(
        f"/api/auctions/{auction_id}/cancel", headers=seller_headers
    )

    assert response.status_code == 403


def test_cancel_is_a_conflict_once_already_cancelled(client: TestClient) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, headers).json()["id"]

    first = client.post(f"/api/auctions/{auction_id}/cancel", headers=headers)
    second = client.post(f"/api/auctions/{auction_id}/cancel", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409


# --------------------------------------------------------------------------
# Sanitisation
# --------------------------------------------------------------------------


def test_html_tags_are_stripped_from_title_and_description(
    client: TestClient,
) -> None:
    headers, _ = signed_in(client, BUYER, "buyer")

    response = create_auction(
        client,
        headers,
        title="Chairs <b>bold</b>",
        description="<script>alert(1)</script>Delivery by Friday",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Chairs bold"
    assert "<script>" not in body["description"]
    assert "Delivery by Friday" in body["description"]
