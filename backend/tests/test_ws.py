"""Live WebSocket feed tests.

Covers the security gates (origin, session, limits), the connect snapshot,
bid/lifecycle fan-out, presence, heartbeat, and the hub's fan-out/pruning.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.models import Auction
from app.models.mixins import utcnow
from app.realtime import AuctionHub
from conftest import COOKIE, register

BUYER = "buyer@example.com"
SELLER = "seller@example.com"

START = 1_000_000
DECREMENT = 5_000

ALLOWED_ORIGIN = "http://localhost:5173"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def sign_in(client: TestClient, email: str, role: str = "buyer") -> None:
    client.cookies.clear()
    response = register(client, email=email, role=role)
    assert response.status_code == 201, response.text


def http_headers(client: TestClient) -> dict[str, str]:
    """Browser HTTP headers: jar supplies the cookie, we add CSRF + Origin."""
    csrf = client.get("/api/auth/me").json()["csrf_token"]
    return {"origin": ALLOWED_ORIGIN, "X-CSRF-Token": csrf}


def socket_headers(
    client: TestClient, *, origin: str | None = ALLOWED_ORIGIN
) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = client.cookies.get(COOKIE)
    if token:
        # The test transport performs an insecure ws:// upgrade, so the Secure
        # cookie is attached explicitly as a real browser would on wss://.
        headers["cookie"] = f"{COOKIE}={token}"
    if origin is not None:
        headers["origin"] = origin
    return headers


def make_auction(client: TestClient, **overrides: Any) -> int:
    payload: dict[str, Any] = {
        "title": "WebSocket auction",
        "description": "live feed",
        "starting_price": START,
        "min_decrement": DECREMENT,
        "duration_hours": 48,
    }
    payload.update(overrides)
    response = client.post("/api/auctions", json=payload, headers=http_headers(client))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def place_bid(
    client: TestClient, auction_id: int, amount: int, key: str
) -> Any:
    return client.post(
        f"/api/auctions/{auction_id}/bids",
        json={"amount": amount, "idempotency_key": key},
        headers=http_headers(client),
    )


def backdate(session_factory: sessionmaker[Session], auction_id: int) -> None:
    now = utcnow()
    with session_factory() as session:
        auction = session.get(Auction, auction_id)
        assert auction is not None
        auction.starts_at = now - timedelta(hours=2)
        auction.ends_at = now - timedelta(minutes=1)
        session.commit()


def drain(websocket) -> None:
    """Consume the snapshot and initial presence frame."""
    assert websocket.receive_json()["type"] == "snapshot"
    assert websocket.receive_json() == {"type": "presence", "viewers": 1}


def connect(client: TestClient, auction_id: int, **kwargs: Any):
    return client.websocket_connect(
        f"/ws/auctions/{auction_id}",
        headers=socket_headers(client, **kwargs),
    )


# --------------------------------------------------------------------------
# Security gates
# --------------------------------------------------------------------------


def test_socket_requires_a_session(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)
    client.cookies.clear()

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with connect(client, auction_id):
            pass

    assert excinfo.value.code == 4401


def test_socket_rejects_a_foreign_origin(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with connect(client, auction_id, origin="https://evil.example"):
            pass

    assert excinfo.value.code == 1008


def test_socket_rejects_an_unknown_auction(client: TestClient) -> None:
    sign_in(client, BUYER)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with connect(client, 999_999):
            pass

    assert excinfo.value.code == 4404


def test_allowed_origin_can_connect(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with connect(client, auction_id) as websocket:
        drain(websocket)


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------


def test_snapshot_carries_the_auction_and_ledger(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)
    sign_in(client, SELLER, "seller")
    assert place_bid(client, auction_id, START - DECREMENT, "ws-snap-1").status_code == 201

    with connect(client, auction_id) as websocket:
        snapshot = websocket.receive_json()
        presence = websocket.receive_json()

    assert snapshot["type"] == "snapshot"
    assert snapshot["auction"]["id"] == auction_id
    assert snapshot["auction"]["lowest_bid"] == START - DECREMENT
    assert snapshot["auction"]["bid_count"] == 1
    assert len(snapshot["bids"]) == 1
    assert snapshot["bids"][0]["amount"] == START - DECREMENT
    assert presence == {"type": "presence", "viewers": 1}


# --------------------------------------------------------------------------
# Live fan-out
# --------------------------------------------------------------------------


def test_new_bid_is_pushed_to_viewers(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with connect(client, auction_id) as viewer:
        drain(viewer)

        sign_in(client, SELLER, "seller")
        assert place_bid(client, auction_id, START - DECREMENT, "ws-live-1").status_code == 201

        message = viewer.receive_json()

    assert message["type"] == "bid"
    assert message["bid"]["amount"] == START - DECREMENT
    assert message["bid"]["seller_email"] == SELLER
    assert message["auction"]["lowest_bid"] == START - DECREMENT


def test_cancel_is_pushed_to_viewers(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with connect(client, auction_id) as viewer:
        drain(viewer)
        response = client.post(
            f"/api/auctions/{auction_id}/cancel", headers=http_headers(client)
        )
        assert response.status_code == 200
        message = viewer.receive_json()

    assert message["type"] == "auction"
    assert message["auction"]["status"] == "cancelled"


def test_expiry_award_is_pushed_to_viewers(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)
    sign_in(client, SELLER, "seller")
    assert place_bid(client, auction_id, START - DECREMENT, "ws-award-1").status_code == 201

    with connect(client, auction_id) as viewer:
        drain(viewer)

        # The deadline sweep runs on the next read; it must notify viewers.
        backdate(session_factory, auction_id)
        client.get(f"/api/auctions/{auction_id}")

        message = viewer.receive_json()

    assert message["type"] == "auction"
    assert message["auction"]["status"] == "awarded"
    assert message["auction"]["winning_bid_id"] is not None


def test_presence_tracks_second_viewer(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with connect(client, auction_id) as first:
        drain(first)
        with connect(client, auction_id) as second:
            assert second.receive_json()["type"] == "snapshot"
            assert second.receive_json() == {"type": "presence", "viewers": 2}
            assert first.receive_json() == {"type": "presence", "viewers": 2}


# --------------------------------------------------------------------------
# Heartbeat and resilience
# --------------------------------------------------------------------------


def test_ping_gets_pong(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with connect(client, auction_id) as websocket:
        drain(websocket)
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}


def test_malformed_frame_does_not_close_the_feed(client: TestClient) -> None:
    sign_in(client, BUYER)
    auction_id = make_auction(client)

    with connect(client, auction_id) as websocket:
        drain(websocket)
        websocket.send_text("definitely not json")
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}


# --------------------------------------------------------------------------
# Hub unit behaviour
# --------------------------------------------------------------------------


class FakeSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[dict[str, Any]] = []
        self.fail = fail

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.messages.append(message)


def test_hub_fans_out_and_prunes_dead_sockets() -> None:
    async def scenario() -> None:
        hub = AuctionHub()
        first, second, dead = FakeSocket(), FakeSocket(), FakeSocket(fail=True)
        await hub.register(1, first)
        await hub.register(1, second)
        await hub.register(1, dead)
        assert hub.viewer_count(1) == 3

        await hub.broadcast(1, {"type": "x"})

        assert first.messages == [{"type": "x"}]
        assert second.messages == [{"type": "x"}]
        assert hub.viewer_count(1) == 2

        assert await hub.unregister(1, first) == 1
        assert await hub.unregister(1, second) == 0
        assert hub.viewer_count(1) == 0

    asyncio.run(scenario())


def test_hub_threadsafe_broadcast_without_a_loop_is_a_noop() -> None:
    hub = AuctionHub()
    # Must not raise when the app is not running / no viewers registered.
    hub.broadcast_threadsafe(1, {"type": "x"})