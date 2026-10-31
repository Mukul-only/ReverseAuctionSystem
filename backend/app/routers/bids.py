"""Bid routes: place, list, and verify the signed ledger.

Reads are public and open, matching the auction itself. Placing a bid requires
the seller role, a CSRF token, and passes a per-account rate limit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..dependencies import require_csrf, require_roles
from ..models import Auction, Role, User, UserSession
from ..realtime import bid_event, hub
from ..schemas.bid import BidCreate, BidOut, ChainVerification
from ..security.ratelimit import SlidingWindowLimiter
from ..services import auction_service, bid_service

settings = get_settings()

router = APIRouter(prefix="/api/auctions", tags=["bids"])

bid_limiter = SlidingWindowLimiter(
    limit=settings.bid_rate_limit,
    window_seconds=settings.bid_rate_window_seconds,
)


def _load_auction(db: Session, auction_id: int) -> Auction:
    try:
        return auction_service.get(db, auction_id)
    except auction_service.AuctionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found."
        ) from None


@router.get("/{auction_id}/bids", response_model=list[BidOut])
def list_bids(
    auction_id: int, db: Session = Depends(get_db)
) -> list[BidOut]:
    _load_auction(db, auction_id)
    return [
        BidOut.model_validate(bid)
        for bid in bid_service.list_for_auction(db, auction_id)
    ]


@router.post(
    "/{auction_id}/bids",
    response_model=BidOut,
    status_code=status.HTTP_201_CREATED,
)
def place_bid(
    auction_id: int,
    payload: BidCreate,
    response: Response,
    seller: User = Depends(require_roles(Role.SELLER)),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> BidOut:
    limit = bid_limiter.check(f"user:{seller.id}")
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many bids. Slow down and try again.",
            headers={"Retry-After": str(limit.retry_after)},
        )

    auction = _load_auction(db, auction_id)
    try:
        bid, created = bid_service.place(
            db,
            auction,
            seller,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
        )
    except bid_service.BidForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot bid on this auction.",
        ) from None
    except (
        bid_service.BidStateError,
        bid_service.BidValidationError,
        bid_service.IdempotencyConflict,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None

    if not created:
        # Idempotent replay: the resource already exists.
        response.status_code = status.HTTP_200_OK
    else:
        # Push the new signed bid to every live viewer of this auction.
        hub.broadcast_threadsafe(auction.id, bid_event(bid, auction))
    return BidOut.model_validate(bid)


@router.get("/{auction_id}/verify", response_model=ChainVerification)
def verify_chain(
    auction_id: int, db: Session = Depends(get_db)
) -> ChainVerification:
    auction = _load_auction(db, auction_id)
    return ChainVerification(**bid_service.verify_chain(db, auction))