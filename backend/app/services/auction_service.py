"""Auction lifecycle and authorization rules."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..models import Auction, AuctionStatus, Role, User
from ..models.mixins import utcnow
from ..security.text import sanitize_plain_text, sanitize_single_line

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


def _finalise_expired(db: Session) -> None:
    """Move open auctions past their deadline to CLOSED.

    Winner resolution is added in the bidding milestone; for now closing is
    purely a state transition.
    """
    db.execute(
        update(Auction)
        .where(
            Auction.status == AuctionStatus.OPEN,
            Auction.ends_at <= utcnow(),
        )
        .values(status=AuctionStatus.CLOSED)
    )
    db.commit()


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
    """Close an ended auction. Only the owning buyer may do this."""
    if auction.buyer_id != actor.id:
        raise AuctionForbidden

    if auction.status in (AuctionStatus.CANCELLED, AuctionStatus.AWARDED):
        raise AuctionStateError("Auction cannot be closed in its current state.")

    if auction.ends_at > utcnow():
        raise AuctionStateError("Auction has not ended yet.")

    if auction.status == AuctionStatus.OPEN:
        auction.status = AuctionStatus.CLOSED
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