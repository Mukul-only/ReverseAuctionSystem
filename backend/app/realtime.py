"""In-process fan-out hub for the live auction feed.

Bids and lifecycle changes are handled by synchronous request handlers that run
in Starlette's threadpool, so the hub also exposes a thread-safe broadcaster
that schedules the coroutine onto the server's event loop (bound at startup).

Single-process only: a real deployment would swap this for Redis pub/sub. That
is an intentional scope cut for the demo and is noted in the docs.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from .schemas.auction import AuctionOut
from .schemas.bid import BidOut

logger = logging.getLogger(__name__)


class AuctionHub:
    """Tracks live sockets per auction and fans out JSON messages."""

    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the loop that owns the sockets (called from lifespan)."""
        self._loop = loop

    def reset(self) -> None:
        """Drop all rooms (used between isolated test clients)."""
        self._rooms.clear()

    def viewer_count(self, auction_id: int) -> int:
        return len(self._rooms.get(auction_id, ()))

    async def register(self, auction_id: int, websocket: WebSocket) -> int:
        room = self._rooms[auction_id]
        room.add(websocket)
        return len(room)

    async def unregister(self, auction_id: int, websocket: WebSocket) -> int:
        room = self._rooms.get(auction_id)
        if room is None:
            return 0
        room.discard(websocket)
        if not room:
            self._rooms.pop(auction_id, None)
            return 0
        return len(room)

    async def broadcast(self, auction_id: int, message: dict[str, Any]) -> None:
        """Send a message to every live viewer of one auction.

        Snapshot the set before iterating: a socket may be removed while we
        await a send. A failing socket is pruned rather than aborting the
        fan-out.
        """
        room = self._rooms.get(auction_id)
        if not room:
            return
        stale: list[WebSocket] = []
        for websocket in list(room):
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 - one dead socket must not stop the rest
                stale.append(websocket)
        for websocket in stale:
            await self.unregister(auction_id, websocket)

    def broadcast_threadsafe(self, auction_id: int, message: dict[str, Any]) -> None:
        """Fan out from a sync handler running in the threadpool."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # Benign cross-thread read of a loop-owned dict: a stale empty result
        # only means we skip scheduling work that would no-op anyway.
        if not self._rooms.get(auction_id):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(auction_id, message), loop
            )
        except RuntimeError:  # pragma: no cover - loop shutting down
            logger.debug(
                "Dropped broadcast for auction %s: loop unavailable", auction_id
            )


hub = AuctionHub()


# ---------------------------------------------------------------------------
# Message builders — one place so the wire format stays consistent.
# ---------------------------------------------------------------------------


def snapshot_event(auction: Any, bids: list[Any]) -> dict[str, Any]:
    return {
        "type": "snapshot",
        "auction": AuctionOut.model_validate(auction).model_dump(mode="json"),
        "bids": [
            BidOut.model_validate(bid).model_dump(mode="json") for bid in bids
        ],
    }


def bid_event(bid: Any, auction: Any) -> dict[str, Any]:
    return {
        "type": "bid",
        "bid": BidOut.model_validate(bid).model_dump(mode="json"),
        "auction": AuctionOut.model_validate(auction).model_dump(mode="json"),
    }


def auction_event(auction: Any) -> dict[str, Any]:
    return {
        "type": "auction",
        "auction": AuctionOut.model_validate(auction).model_dump(mode="json"),
    }


def presence_event(viewers: int) -> dict[str, Any]:
    return {"type": "presence", "viewers": viewers}