"""Hardening tests: headers, origin/CSRF gates, size limits, injection, IDOR."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from conftest import csrf_headers, register

BAD_ORIGIN = "https://evil.example"
BUYER = "hard-buyer@example.com"
BUYER2 = "hard-buyer2@example.com"
SELLER = "hard-seller@example.com"

AUCTION = {
    "title": "Security testing lot",
    "description": "defensive",
    "starting_price": 500_000,
    "min_decrement": 1_000,
    "duration_hours": 24,
}


def sign_in(client: TestClient, email: str, role: str) -> dict[str, str]:
    client.cookies.clear()
    register(client, email=email, role=role)
    return csrf_headers(client)


# --------------------------------------------------------------------------
# Response headers
# --------------------------------------------------------------------------


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")


# --------------------------------------------------------------------------
# Origin and CSRF
# --------------------------------------------------------------------------


def test_mutation_from_a_foreign_origin_is_rejected(client: TestClient) -> None:
    headers = sign_in(client, BUYER, "buyer")
    headers["Origin"] = BAD_ORIGIN

    response = client.post("/api/auctions", json=AUCTION, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Origin not allowed."


def test_mutation_without_csrf_is_rejected(client: TestClient) -> None:
    sign_in(client, BUYER, "buyer")

    response = client.post("/api/auctions", json=AUCTION)

    assert response.status_code == 403


def test_login_csrf_is_guarded_by_origin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": BUYER, "password": "irrelevant"},
        headers={"Origin": BAD_ORIGIN},
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Request size
# --------------------------------------------------------------------------


def test_oversized_body_is_refused(client: TestClient) -> None:
    limit = get_settings().max_request_bytes

    response = client.post(
        "/api/auth/login",
        content=b"x" * (limit + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


# --------------------------------------------------------------------------
# Injection
# --------------------------------------------------------------------------


def test_sql_injection_in_login_does_not_authenticate(client: TestClient) -> None:
    sign_in(client, BUYER, "buyer")
    client.cookies.clear()

    response = client.post(
        "/api/auth/login",
        json={"email": BUYER, "password": "' OR '1'='1' --"},
    )

    assert response.status_code == 401


def test_sql_injection_in_email_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "' OR 1=1 --", "password": "whatever"},
    )

    assert response.status_code == 422


def test_stored_xss_is_stripped(client: TestClient) -> None:
    headers = sign_in(client, BUYER, "buyer")
    payload = {**AUCTION, "title": "<script>alert(1)</script>Office chairs"}

    response = client.post("/api/auctions", json=payload, headers=headers)

    assert response.status_code == 201
    title = response.json()["title"]
    assert "<script>" not in title
    assert "Office chairs" in title


def test_control_characters_are_stripped(client: TestClient) -> None:
    headers = sign_in(client, BUYER, "buyer")
    payload = {**AUCTION, "description": "line\x00one\x07two"}

    response = client.post("/api/auctions", json=payload, headers=headers)

    assert response.status_code == 201
    assert "\x00" not in response.json()["description"]


# --------------------------------------------------------------------------
# Authorization / IDOR
# --------------------------------------------------------------------------


def test_another_buyer_cannot_close_an_auction(client: TestClient) -> None:
    owner = sign_in(client, BUYER, "buyer")
    auction_id = client.post("/api/auctions", json=AUCTION, headers=owner).json()["id"]

    intruder = sign_in(client, BUYER2, "buyer")
    response = client.post(f"/api/auctions/{auction_id}/cancel", headers=intruder)

    assert response.status_code == 403


def test_a_seller_cannot_cancel_an_auction(client: TestClient) -> None:
    owner = sign_in(client, BUYER, "buyer")
    auction_id = client.post("/api/auctions", json=AUCTION, headers=owner).json()["id"]

    seller = sign_in(client, SELLER, "seller")
    response = client.post(f"/api/auctions/{auction_id}/cancel", headers=seller)

    assert response.status_code == 403


def test_a_buyer_cannot_bid(client: TestClient) -> None:
    headers = sign_in(client, BUYER, "buyer")
    auction_id = client.post("/api/auctions", json=AUCTION, headers=headers).json()["id"]

    response = client.post(
        f"/api/auctions/{auction_id}/bids",
        json={"amount": 490_000, "idempotency_key": "buyer-bid-1"},
        headers=headers,
    )

    assert response.status_code == 403


def test_unknown_auction_is_404(client: TestClient) -> None:
    assert client.get("/api/auctions/999999").status_code == 404


# --------------------------------------------------------------------------
# Abuse controls
# --------------------------------------------------------------------------


def test_login_attempts_are_rate_limited(client: TestClient) -> None:
    sign_in(client, BUYER, "buyer")
    client.cookies.clear()

    statuses = [
        client.post(
            "/api/auth/login",
            json={"email": BUYER, "password": "wrong-password-attempt"},
        ).status_code
        for _ in range(12)
    ]

    assert 429 in statuses