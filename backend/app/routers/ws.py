"""Authenticated WebSocket feed for a single auction.

Security posture:

- **Origin allowlist (CSWSH defense).** Browsers always send ``Origin`` on a
  WebSocket handshake. A mismatch is closed before the upgrade is accepted, so
  a hostile page cannot ride the victim's session cookie.
- **Session required.** A valid server-side session cookie must be presented;
  unauthenticated sockets are closed with ``4401`` and the SPA falls back to
  polling. Auction reads are public, so any signed-in user may watch.
- **Public data only.** The feed carries auction state and public bid rows —
  never per-user secrets.

The socket is read-only apart from an application-level ping/pong heartbeat.
Bid and lifecycle writes stay on the CSRF-protected HTTP routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..realtime import auction_event, hub, presence_event, snapshot_event
from ..security.sessions import get_session_by_token
from ..services import auction_service, bid_service

settings = get_settings()

router = APIRouter(tags=["realtime"])

# RFC 6455 codes plus a 4xxx application range.
POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013
UNAUTHENTICATED = 4401
AUCTION_NOT_FOUND = 4404

MAX_VIEWERS_PER_AUCTION = 200


def origin_allowed(websocket: WebSocket) -> bool:
    """Mirror the HTTP Origin policy for the handshake."""
    origin = websocket.headers.get("origin")
    return origin is None or origin in settings.allowed_origins


@router.websocket("/ws/auctions/{auction_id}")
async def auction_feed(
    websocket: WebSocket,
    auction_id: int,
    db: Session = Depends(get_db),
) -> None:
    if not origin_allowed(websocket):
        await websocket.close(code=POLICY_VIOLATION, reason="Origin not allowed.")
        return

    session = get_session_by_token(
        db, websocket.cookies.get(settings.session_cookie_name)
    )
    if session is None:
        await websocket.close(
            code=UNAUTHENTICATED, reason="Authentication required."
        )
        return

    try:
        auction = auction_service.get(db, auction_id)
    except auction_service.AuctionNotFound:
        await websocket.close(
            code=AUCTION_NOT_FOUND, reason="Auction not found."
        )
        return

    if hub.viewer_count(auction_id) >= MAX_VIEWERS_PER_AUCTION:
        await websocket.close(
            code=TRY_AGAIN_LATER, reason="Too many viewers for this auction."
        )
        return

    await websocket.accept()
    viewers = await hub.register(auction_id, websocket)

    await websocket.send_json(
        snapshot_event(auction, bid_service.list_for_auction(db, auction_id))
    )
    await hub.broadcast(auction_id, presence_event(viewers))

    try:
        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                # Malformed frame: ignore it and keep the feed alive.
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        remaining = await hub.unregister(auction_id, websocket)
        await hub.broadcast(auction_id, presence_event(remaining))