"""Auction lifecycle and authorization rules."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Auction, AuctionStatus, Role, User
from ..models.mixins import utcnow
from ..realtime import auction_event, hub
from ..security.text import sanitize_plain_text, sanitize_single_line
from . import audit_service

_EAGER = (
    selectinload(Auction.buyer),
    selectinload(Auction.bids),
)


class AuctionError(Exception):
    """Base class for auction domain errors."""


class AuctionNotFound(AuctionError):
    pass


class AuctionStateError(AuctionError):
    pass


class AuctionForbidden(AuctionError):
    pass


def _resolve_winner(auction: Auction) -> None:
    """Award the lowest bid, or close an auction that received none.

    Bids are strictly descending by construction, but we still take the
    minimum and break ties by id so the result is deterministic.
    """
    lowest = min(auction.bids, key=lambda bid: (bid.amount, bid.id), default=None)
    if lowest is None:
        auction.winning_bid_id = None
        auction.status = AuctionStatus.CLOSED
    else:
        auction.winning_bid_id = lowest.id
        auction.status = AuctionStatus.AWARDED


def _finalise_expired(db: Session) -> None:
    """Close and resolve every open auction whose deadline has passed.

    This runs on reads so a demo never leaves an auction stuck past its end
    time. It is idempotent: only OPEN rows are touched.
    """
    expired = list(
        db.scalars(
            select(Auction)
            .where(
                Auction.status == AuctionStatus.OPEN,
                Auction.ends_at <= utcnow(),
            )
            .options(selectinload(Auction.bids))
        )
    )
    if not expired:
        return

    for auction in expired:
        _resolve_winner(auction)
    db.commit()

    # A close caused by the deadline has no HTTP handler to broadcast from, so
    # notify live viewers here. This runs in a worker thread; the hub schedules
    # the coroutine back onto the event loop.
    for auction in expired:
        hub.broadcast_threadsafe(auction.id, auction_event(auction))
        try:
            audit_service.record(
                db,
                actor_id=None,
                action="auction.ended",
                entity_type="auction",
                entity_id=auction.id,
                metadata={
                    "status": auction.status.value,
                    "winning_bid_id": auction.winning_bid_id,
                    "trigger": "deadline",
                },
            )
        except Exception:  # noqa: BLE001 - auditing must not break the sweep
            db.rollback()


def list_open(db: Session) -> list[Auction]:
    _finalise_expired(db)
    statement = (
        select(Auction)
        .where(Auction.status == AuctionStatus.OPEN)
        .order_by(Auction.ends_at.asc(), Auction.id.asc())
        .options(*_EAGER)
    )
    return list(db.scalars(statement))


def list_for_user(db: Session, user_id: int) -> list[Auction]:
    _finalise_expired(db)
    statement = (
        select(Auction)
        .where(Auction.buyer_id == user_id)
        .order_by(Auction.created_at.desc(), Auction.id.desc())
        .options(*_EAGER)
    )
    return list(db.scalars(statement))


def get(db: Session, auction_id: int) -> Auction:
    _finalise_expired(db)
    auction = db.get(Auction, auction_id, options=list(_EAGER))
    if auction is None:
        raise AuctionNotFound
    return auction


def create(
    db: Session,
    buyer: User,
    *,
    title: str,
    description: str,
    starting_price: int,
    min_decrement: int,
    currency: str,
    duration_hours: int,
) -> Auction:
    if buyer.role != Role.BUYER:
        raise AuctionForbidden

    now = utcnow()
    auction = Auction(
        buyer_id=buyer.id,
        title=sanitize_single_line(title),
        description=sanitize_plain_text(description),
        starting_price=starting_price,
        min_decrement=min_decrement,
        currency=currency,
        starts_at=now,
        ends_at=now + timedelta(hours=duration_hours),
        status=AuctionStatus.OPEN,
    )
    db.add(auction)
    db.commit()
    db.refresh(auction)
    return auction


def close(db: Session, auction: Auction, actor: User) -> Auction:
    """Close an ended auction and award it to the lowest bid.

    Only the owning buyer may do this. Calling it twice is harmless: an auction
    already finalised by the expiry sweep is returned unchanged.
    """
    if auction.buyer_id != actor.id:
        raise AuctionForbidden

    if auction.status == AuctionStatus.CANCELLED:
        raise AuctionStateError("Auction cannot be closed in its current state.")

    if auction.status in (AuctionStatus.CLOSED, AuctionStatus.AWARDED):
        return auction

    if auction.ends_at > utcnow():
        raise AuctionStateError("Auction has not ended yet.")

    _resolve_winner(auction)
    db.commit()
    return auction


def cancel(db: Session, auction: Auction, actor: User) -> Auction:
    """Cancel an active auction. The owner or an admin may do this."""
    if actor.role != Role.ADMIN and auction.buyer_id != actor.id:
        raise AuctionForbidden

    if auction.status not in (AuctionStatus.OPEN, AuctionStatus.DRAFT):
        raise AuctionStateError("Auction cannot be cancelled in its current state.")

    auction.status = AuctionStatus.CANCELLED
    db.commit()
    return auction