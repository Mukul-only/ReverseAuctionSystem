"""Descending bid engine with HMAC signing and a per-auction hash chain."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import Auction, AuctionStatus, Bid, Role, User
from ..models.mixins import utcnow
from ..security.crypto import (
    auction_signing_key,
    canonical_bid_payload,
    sign_payload,
    signature_matches,
)

NONCE_BYTES = 16


class BidError(Exception):
    """Base class for bid domain errors."""


class BidForbidden(BidError):
    pass


class BidStateError(BidError):
    pass


class BidValidationError(BidError):
    pass


class IdempotencyConflict(BidError):
    pass


def list_for_auction(db: Session, auction_id: int) -> list[Bid]:
    statement = (
        select(Bid)
        .where(Bid.auction_id == auction_id)
        .order_by(Bid.id.asc())
        .options(selectinload(Bid.seller))
    )
    return list(db.scalars(statement))


def maximum_next_amount(auction: Auction) -> int:
    """The highest amount a new bid may carry.

    With no bids the ceiling is the starting price minus one decrement; after
    that it is the current lowest minus one decrement.
    """
    if auction.bids:
        base = min(bid.amount for bid in auction.bids)
    else:
        base = auction.starting_price
    return base - auction.min_decrement


def place(
    db: Session,
    auction: Auction,
    seller: User,
    *,
    amount: int,
    idempotency_key: str,
) -> tuple[Bid, bool]:
    """Place a descending bid.

    Returns ``(bid, created)``. A replay with the same idempotency key and
    payload returns the original row with ``created=False``.
    """
    if seller.role != Role.SELLER:
        raise BidForbidden
    # Defense in depth: roles already make this impossible, but never let an
    # owner bid against their own requirement.
    if auction.buyer_id == seller.id:
        raise BidForbidden

    existing = db.scalar(
        select(Bid).where(
            Bid.auction_id == auction.id,
            Bid.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.seller_id != seller.id or existing.amount != amount:
            raise IdempotencyConflict(
                "This idempotency key was already used for a different bid."
            )
        return existing, False

    if auction.status != AuctionStatus.OPEN:
        raise BidStateError("Auction is not open for bidding.")
    if auction.ends_at <= utcnow():
        raise BidStateError("Auction has already ended.")

    ceiling = maximum_next_amount(auction)
    if ceiling <= 0:
        raise BidValidationError("No valid bid range remains for this auction.")
    if amount > ceiling:
        raise BidValidationError(
            f"Bid must be at most {ceiling} paise: below the current lowest "
            "by the minimum decrement."
        )

    previous = db.scalar(
        select(Bid)
        .where(Bid.auction_id == auction.id)
        .order_by(Bid.id.desc())
        .limit(1)
    )
    prev_hash = previous.signature if previous is not None else None

    created_at = utcnow()
    nonce = secrets.token_hex(NONCE_BYTES)
    payload = canonical_bid_payload(
        auction_id=auction.id,
        seller_id=seller.id,
        amount=amount,
        nonce=nonce,
        created_at=created_at,
        prev_hash=prev_hash,
    )
    signature = sign_payload(auction_signing_key(auction.id), payload)

    bid = Bid(
        auction_id=auction.id,
        seller_id=seller.id,
        amount=amount,
        nonce=nonce,
        idempotency_key=idempotency_key,
        prev_hash=prev_hash,
        signature=signature,
        created_at=created_at,
    )
    db.add(bid)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        # A concurrent retry may have won the race. Replay it if identical.
        replay = db.scalar(
            select(Bid).where(
                Bid.auction_id == auction.id,
                Bid.idempotency_key == idempotency_key,
            )
        )
        if (
            replay is not None
            and replay.seller_id == seller.id
            and replay.amount == amount
        ):
            return replay, False
        raise BidValidationError(
            "Bid rejected: another bid arrived first. Refresh and bid lower."
        ) from error

    db.refresh(bid)
    # The relationship was loaded before the insert; make the next read see
    # this bid (important when several bids are placed in one session).
    db.expire(auction, ["bids"])
    return bid, True


def verify_chain(db: Session, auction: Auction) -> dict[str, object]:
    """Recompute every signature and link, returning a verification report."""
    bids = list_for_auction(db, auction.id)
    key = auction_signing_key(auction.id)
    previous_signature: str | None = None
    checked = 0

    for bid in bids:
        payload = canonical_bid_payload(
            auction_id=bid.auction_id,
            seller_id=bid.seller_id,
            amount=bid.amount,
            nonce=bid.nonce,
            created_at=bid.created_at,
            prev_hash=bid.prev_hash,
        )
        if not signature_matches(key, payload, bid.signature):
            return {
                "auction_id": auction.id,
                "bid_count": len(bids),
                "checked": checked,
                "valid": False,
                "first_invalid_bid_id": bid.id,
                "reason": "Signature mismatch: bid data was altered.",
            }

        if (bid.prev_hash or None) != previous_signature:
            return {
                "auction_id": auction.id,
                "bid_count": len(bids),
                "checked": checked,
                "valid": False,
                "first_invalid_bid_id": bid.id,
                "reason": "Chain link mismatch: a bid was removed or reordered.",
            }

        previous_signature = bid.signature
        checked += 1

    return {
        "auction_id": auction.id,
        "bid_count": len(bids),
        "checked": checked,
        "valid": True,
        "first_invalid_bid_id": None,
        "reason": None,
    }