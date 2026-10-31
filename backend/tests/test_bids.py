"""Signed bid ledger tests.

Covers descending rules, role/CSRF gates, idempotency, HMAC signatures, chain
verification, tamper detection, and winner resolution.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Auction, Bid, Role
from app.models.mixins import utcnow
from app.services import auth_service
from conftest import PASSWORD, register

BUYER = "buyer@example.com"
SELLER = "seller@example.com"
SELLER2 = "seller2@example.com"
ADMIN = "admin@example.com"

START = 1_000_000
DECREMENT = 5_000


def csrf_of(response) -> str:
    return response.json()["csrf_token"]


def signed_in(client: TestClient, email: str, role: str) -> dict[str, str]:
    client.cookies.clear()
    token = csrf_of(register(client, email=email, role=role))
    return {"X-CSRF-Token": token}


def login_existing(client: TestClient, email: str) -> dict[str, str]:
    client.cookies.clear()
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"X-CSRF-Token": csrf_of(response)}


def sign_in_admin(
    client: TestClient, session_factory: sessionmaker[Session]
) -> dict[str, str]:
    with session_factory() as session:
        auth_service.register_user(
            session, email=ADMIN, password=PASSWORD, role=Role.ADMIN
        )
    return login_existing(client, ADMIN)


def auction_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Bulk chairs",
        "description": "120 units",
        "starting_price": START,
        "min_decrement": DECREMENT,
        "duration_hours": 48,
    }
    payload.update(overrides)
    return payload


def create_auction(
    client: TestClient, headers: dict[str, str], **overrides: Any
):
    return client.post(
        "/api/auctions", json=auction_payload(**overrides), headers=headers
    )


def place_bid(
    client: TestClient,
    headers: dict[str, str],
    auction_id: int,
    amount: int,
    *,
    key: str = "idem-key-0001",
):
    return client.post(
        f"/api/auctions/{auction_id}/bids",
        json={"amount": amount, "idempotency_key": key},
        headers=headers,
    )


def backdate(
    session_factory: sessionmaker[Session], auction_id: int
) -> None:
    now = utcnow()
    with session_factory() as session:
        auction = session.get(Auction, auction_id)
        assert auction is not None
        auction.starts_at = now - timedelta(hours=2)
        auction.ends_at = now - timedelta(minutes=1)
        session.commit()


# --------------------------------------------------------------------------
# Placement and descending rules
# --------------------------------------------------------------------------


def test_seller_places_the_first_bid(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    seller_headers = signed_in(client, SELLER, "seller")
    response = place_bid(
        client, seller_headers, auction_id, START - DECREMENT
    )

    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == START - DECREMENT
    assert body["seller_email"] == SELLER
    assert body["prev_hash"] is None
    assert len(body["signature"]) == 64
    int(body["signature"], 16)  # hex
    assert len(body["nonce"]) == 32
    assert "idempotency_key" not in body


def test_first_bid_must_respect_the_decrement(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    response = place_bid(
        client, seller_headers, auction_id, START - DECREMENT + 1
    )

    assert response.status_code == 409


def test_each_bid_must_beat_the_current_lowest(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    assert (
        place_bid(
            client, seller_headers, auction_id, START - DECREMENT, key="seq-key-1"
        ).status_code
        == 201
    )

    # Ceiling is now 990,000.
    too_high = place_bid(
        client, seller_headers, auction_id, 990_001, key="seq-key-2"
    )
    assert too_high.status_code == 409

    at_ceiling = place_bid(
        client, seller_headers, auction_id, 990_000, key="seq-key-3"
    )
    assert at_ceiling.status_code == 201


def test_second_bid_links_to_the_first_signature(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    first_seller = signed_in(client, SELLER, "seller")
    first = place_bid(
        client, first_seller, auction_id, 995_000, key="chain-key-1"
    ).json()

    second_seller = signed_in(client, SELLER2, "seller")
    second = place_bid(
        client, second_seller, auction_id, 990_000, key="chain-key-2"
    ).json()

    assert second["prev_hash"] == first["signature"]


def test_bid_on_a_cancelled_auction_is_rejected(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    client.post(f"/api/auctions/{auction_id}/cancel", headers=buyer_headers)

    seller_headers = signed_in(client, SELLER, "seller")
    response = place_bid(client, seller_headers, auction_id, 900_000)

    assert response.status_code == 409


def test_bid_after_the_deadline_is_rejected(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    backdate(session_factory, auction_id)

    seller_headers = signed_in(client, SELLER, "seller")
    response = place_bid(client, seller_headers, auction_id, 900_000)

    assert response.status_code == 409


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


def test_buyer_cannot_bid(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    response = place_bid(client, buyer_headers, auction_id, 900_000)

    assert response.status_code == 403


def test_admin_cannot_bid(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    admin_headers = sign_in_admin(client, session_factory)
    response = place_bid(client, admin_headers, auction_id, 900_000)

    assert response.status_code == 403


def test_anonymous_cannot_bid(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    client.cookies.clear()

    response = client.post(
        f"/api/auctions/{auction_id}/bids",
        json={"amount": 900_000, "idempotency_key": "anon-key-1"},
    )

    assert response.status_code == 401


def test_placing_a_bid_requires_csrf(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    signed_in(client, SELLER, "seller")

    response = client.post(
        f"/api/auctions/{auction_id}/bids",
        json={"amount": 900_000, "idempotency_key": "csrf-key-1"},
    )

    assert response.status_code == 403


def test_bid_input_is_validated(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    assert (
        place_bid(client, seller_headers, auction_id, 0, key="zero-key-1").status_code
        == 422
    )
    assert (
        place_bid(client, seller_headers, auction_id, 900_000, key="short").status_code
        == 422
    )


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_replaying_a_key_returns_the_original_bid(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    first = place_bid(
        client, seller_headers, auction_id, 995_000, key="replay-key-1"
    )
    replay = place_bid(
        client, seller_headers, auction_id, 995_000, key="replay-key-1"
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    ledger = client.get(f"/api/auctions/{auction_id}/bids").json()
    assert len(ledger) == 1


def test_reusing_a_key_with_a_different_amount_conflicts(
    client: TestClient,
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    assert (
        place_bid(
            client, seller_headers, auction_id, 995_000, key="reuse-key-1"
        ).status_code
        == 201
    )
    response = place_bid(
        client, seller_headers, auction_id, 990_000, key="reuse-key-1"
    )

    assert response.status_code == 409


def test_idempotency_keys_are_scoped_to_the_bidder(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    first_seller = signed_in(client, SELLER, "seller")
    assert (
        place_bid(
            client, first_seller, auction_id, 995_000, key="shared-key-1"
        ).status_code
        == 201
    )

    second_seller = signed_in(client, SELLER2, "seller")
    response = place_bid(
        client, second_seller, auction_id, 990_000, key="shared-key-1"
    )

    assert response.status_code == 409


# --------------------------------------------------------------------------
# Chain verification and tamper detection
# --------------------------------------------------------------------------


def test_verify_reports_a_healthy_chain(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    place_bid(client, seller_headers, auction_id, 995_000, key="verify-key-1")
    place_bid(client, seller_headers, auction_id, 990_000, key="verify-key-2")

    response = client.get(f"/api/auctions/{auction_id}/verify")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["bid_count"] == 2
    assert body["checked"] == 2
    assert body["first_invalid_bid_id"] is None


def test_verify_of_an_empty_ledger_is_valid(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    body = client.get(f"/api/auctions/{auction_id}/verify").json()

    assert body["valid"] is True
    assert body["bid_count"] == 0
    assert body["checked"] == 0


def test_verify_detects_an_altered_signature(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    place_bid(client, seller_headers, auction_id, 995_000, key="tamper-key-1")
    second = place_bid(
        client, seller_headers, auction_id, 990_000, key="tamper-key-2"
    ).json()

    # Simulate a database attacker: the guard trigger must be removed first.
    with session_factory() as session:
        session.execute(text("DROP TRIGGER bids_no_update"))
        bid = session.get(Bid, second["id"])
        assert bid is not None
        bid.signature = "f" * 64
        session.commit()

    body = client.get(f"/api/auctions/{auction_id}/verify").json()

    assert body["valid"] is False
    assert body["first_invalid_bid_id"] == second["id"]
    assert "Signature" in body["reason"]
    assert body["checked"] == 1


def test_verify_detects_a_removed_bid(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    place_bid(client, seller_headers, auction_id, 995_000, key="delete-key-1")
    middle = place_bid(
        client, seller_headers, auction_id, 990_000, key="delete-key-2"
    ).json()
    third = place_bid(
        client, seller_headers, auction_id, 985_000, key="delete-key-3"
    ).json()

    with session_factory() as session:
        session.execute(text("DROP TRIGGER bids_no_delete"))
        session.execute(
            text("DELETE FROM bids WHERE id = :bid_id"),
            {"bid_id": middle["id"]},
        )
        session.commit()

    body = client.get(f"/api/auctions/{auction_id}/verify").json()

    assert body["valid"] is False
    assert body["first_invalid_bid_id"] == third["id"]
    assert "Chain link" in body["reason"]


# --------------------------------------------------------------------------
# Winner resolution
# --------------------------------------------------------------------------


def test_expiry_awards_the_lowest_bid_on_read(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    place_bid(client, seller_headers, auction_id, 995_000, key="win-key-1")
    lowest = place_bid(
        client, seller_headers, auction_id, 990_000, key="win-key-2"
    ).json()
    backdate(session_factory, auction_id)

    body = client.get(f"/api/auctions/{auction_id}").json()

    assert body["status"] == "awarded"
    assert body["winning_bid_id"] == lowest["id"]


def test_owner_close_awards_the_lowest_bid(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]

    seller_headers = signed_in(client, SELLER, "seller")
    place_bid(client, seller_headers, auction_id, 995_000, key="close-key-1")
    lowest = place_bid(
        client, seller_headers, auction_id, 990_000, key="close-key-2"
    ).json()

    backdate(session_factory, auction_id)
    buyer_headers = login_existing(client, BUYER)

    response = client.post(
        f"/api/auctions/{auction_id}/close", headers=buyer_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "awarded"
    assert response.json()["winning_bid_id"] == lowest["id"]


def test_close_without_bids_stays_closed(
    client: TestClient, session_factory
) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(client, buyer_headers).json()["id"]
    backdate(session_factory, auction_id)

    response = client.post(
        f"/api/auctions/{auction_id}/close", headers=buyer_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["winning_bid_id"] is None


# --------------------------------------------------------------------------
# Abuse controls
# --------------------------------------------------------------------------


def test_bid_placement_is_rate_limited(client: TestClient) -> None:
    buyer_headers = signed_in(client, BUYER, "buyer")
    auction_id = create_auction(
        client,
        buyer_headers,
        starting_price=10_000_000,
        min_decrement=1,
    ).json()["id"]
    seller_headers = signed_in(client, SELLER, "seller")

    for index in range(1, 31):
        response = place_bid(
            client,
            seller_headers,
            auction_id,
            10_000_000 - index,
            key=f"rate-key-{index:03d}",
        )
        assert response.status_code == 201

    blocked = place_bid(
        client, seller_headers, auction_id, 10_000_000 - 31, key="rate-key-031"
    )

    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers