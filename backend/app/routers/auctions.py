"""Auction routes.

Authorization model:
- Any visitor may list and read auctions.
- Only buyers may create.
- Only the owning buyer may close.
- The owning buyer or an admin may cancel.
Every mutation requires a CSRF token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import get_current_user, require_csrf, require_roles
from ..models import Auction, Role, User, UserSession
from ..realtime import auction_event, hub
from ..schemas.auction import AuctionCreate, AuctionOut
from ..security.ratelimit import SlidingWindowLimiter
from ..services import auction_service

router = APIRouter(prefix="/api/auctions", tags=["auctions"])

create_limiter = SlidingWindowLimiter(limit=30, window_seconds=3600)


def _load(db: Session, auction_id: int) -> Auction:
    try:
        return auction_service.get(db, auction_id)
    except auction_service.AuctionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found."
        ) from None


@router.get("", response_model=list[AuctionOut])
def list_auctions(db: Session = Depends(get_db)) -> list[AuctionOut]:
    return [
        AuctionOut.model_validate(auction)
        for auction in auction_service.list_open(db)
    ]


@router.get("/mine", response_model=list[AuctionOut])
def list_my_auctions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuctionOut]:
    return [
        AuctionOut.model_validate(auction)
        for auction in auction_service.list_for_user(db, user.id)
    ]


@router.post(
    "",
    response_model=AuctionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_auction(
    payload: AuctionCreate,
    user: User = Depends(require_roles(Role.BUYER)),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AuctionOut:
    limit = create_limiter.check(f"user:{user.id}")
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many auctions created. Try again later.",
            headers={"Retry-After": str(limit.retry_after)},
        )

    auction = auction_service.create(
        db,
        user,
        title=payload.title,
        description=payload.description,
        starting_price=payload.starting_price,
        min_decrement=payload.min_decrement,
        currency=payload.currency,
        duration_hours=payload.duration_hours,
    )
    return AuctionOut.model_validate(auction)


@router.get("/{auction_id}", response_model=AuctionOut)
def get_auction(auction_id: int, db: Session = Depends(get_db)) -> AuctionOut:
    return AuctionOut.model_validate(_load(db, auction_id))


@router.post("/{auction_id}/close", response_model=AuctionOut)
def close_auction(
    auction_id: int,
    user: User = Depends(get_current_user),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AuctionOut:
    auction = _load(db, auction_id)
    try:
        auction_service.close(db, auction, user)
    except auction_service.AuctionForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the auction owner can close this auction.",
        ) from None
    except auction_service.AuctionStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None
    hub.broadcast_threadsafe(auction.id, auction_event(auction))
    return AuctionOut.model_validate(auction)


@router.post("/{auction_id}/cancel", response_model=AuctionOut)
def cancel_auction(
    auction_id: int,
    user: User = Depends(get_current_user),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AuctionOut:
    auction = _load(db, auction_id)
    try:
        auction_service.cancel(db, auction, user)
    except auction_service.AuctionForbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot cancel this auction.",
        ) from None
    except auction_service.AuctionStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None
    hub.broadcast_threadsafe(auction.id, auction_event(auction))
    return AuctionOut.model_validate(auction)
