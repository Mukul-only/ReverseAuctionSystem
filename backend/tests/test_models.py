from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Auction,
    AuctionStatus,
    AuditEvent,
    Bid,
    Role,
    User,
    UserSession,
)
from app.models.mixins import utcnow

PREV_HASH = "0" * 64
SIGNATURE = "a" * 64


def make_user(
    db: Session, email: str = "user@example.com", role: Role = Role.BUYER
) -> User:
    user = User(email=email, password_hash="argon2-hash", role=role)
    db.add(user)
    db.commit()
    return user


def make_auction(db: Session, buyer: User, **overrides: object) -> Auction:
    now = utcnow()
    values: dict[str, object] = {
        "buyer_id": buyer.id,
        "title": "Bulk chairs",
        "description": "120 units",
        "starting_price": 1_000_000,
        "min_decrement": 5_000,
        "starts_at": now - timedelta(hours=1),
        "ends_at": now + timedelta(days=2),
        "status": AuctionStatus.OPEN,
    }
    values.update(overrides)
    auction = Auction(**values)  # type: ignore[arg-type]
    db.add(auction)
    db.commit()
    return auction


def make_bid(
    db: Session,
    auction: Auction,
    seller: User,
    *,
    amount: int = 900_000,
    key: str = "key-1",
    nonce: str = "nonce-1",
) -> Bid:
    bid = Bid(
        auction_id=auction.id,
        seller_id=seller.id,
        amount=amount,
        nonce=nonce,
        idempotency_key=key,
        prev_hash=PREV_HASH,
        signature=SIGNATURE,
    )
    db.add(bid)
    db.commit()
    return bid


def make_audit_event(db: Session, action: str = "login") -> AuditEvent:
    event = AuditEvent(action=action, metadata_json="{}", hash="h" * 64)
    db.add(event)
    db.commit()
    return event


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


def test_email_is_normalised(db: Session) -> None:
    user = make_user(db, email="  Mixed@Example.COM ")
    assert user.email == "mixed@example.com"


def test_email_is_unique(db: Session) -> None:
    make_user(db, email="dup@example.com")
    with pytest.raises(IntegrityError):
        make_user(db, email="DUP@example.com")
    db.rollback()


# --------------------------------------------------------------------------
# Auctions
# --------------------------------------------------------------------------


def test_auction_rejects_non_positive_price(db: Session) -> None:
    buyer = make_user(db)
    with pytest.raises(IntegrityError):
        make_auction(db, buyer, starting_price=0)
    db.rollback()


def test_auction_rejects_inverted_window(db: Session) -> None:
    buyer = make_user(db)
    now = utcnow()
    with pytest.raises(IntegrityError):
        make_auction(db, buyer, starts_at=now, ends_at=now)
    db.rollback()


def test_auction_bids_relationship(db: Session) -> None:
    buyer = make_user(db)
    seller = make_user(db, email="seller@example.com", role=Role.SELLER)
    auction = make_auction(db, buyer)
    bid = make_bid(db, auction, seller)

    db.refresh(auction)
    assert [item.id for item in auction.bids] == [bid.id]


# --------------------------------------------------------------------------
# Bids
# --------------------------------------------------------------------------


def test_bid_idempotency_key_is_unique_per_auction(db: Session) -> None:
    buyer = make_user(db)
    seller = make_user(db, email="seller@example.com", role=Role.SELLER)
    auction = make_auction(db, buyer)

    make_bid(db, auction, seller, key="dup", nonce="n1")
    with pytest.raises(IntegrityError):
        make_bid(db, auction, seller, amount=800_000, key="dup", nonce="n2")
    db.rollback()


def test_bid_rejects_non_positive_amount(db: Session) -> None:
    buyer = make_user(db)
    seller = make_user(db, email="seller@example.com", role=Role.SELLER)
    auction = make_auction(db, buyer)

    with pytest.raises(IntegrityError):
        make_bid(db, auction, seller, amount=0, nonce="n-zero")
    db.rollback()


def test_bids_are_immutable_on_update(db: Session) -> None:
    buyer = make_user(db)
    seller = make_user(db, email="seller@example.com", role=Role.SELLER)
    auction = make_auction(db, buyer)
    bid = make_bid(db, auction, seller)

    bid.amount = 1
    with pytest.raises(IntegrityError, match="immutable"):
        db.commit()
    db.rollback()


def test_bids_are_immutable_on_delete(db: Session) -> None:
    buyer = make_user(db)
    seller = make_user(db, email="seller@example.com", role=Role.SELLER)
    auction = make_auction(db, buyer)
    bid = make_bid(db, auction, seller)
    bid_id = bid.id

    db.delete(bid)
    with pytest.raises(IntegrityError, match="immutable"):
        db.commit()
    db.rollback()

    assert db.get(Bid, bid_id) is not None


# --------------------------------------------------------------------------
# Audit events
# --------------------------------------------------------------------------


def test_audit_events_are_append_only_on_update(db: Session) -> None:
    event = make_audit_event(db)
    event.action = "tampered"

    with pytest.raises(IntegrityError, match="append-only"):
        db.commit()
    db.rollback()


def test_audit_events_are_append_only_on_delete(db: Session) -> None:
    event = make_audit_event(db)
    event_id = event.seq

    db.delete(event)
    with pytest.raises(IntegrityError, match="append-only"):
        db.commit()
    db.rollback()

    assert db.get(AuditEvent, event_id) is not None


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------


def test_sessions_cascade_when_user_is_deleted(db: Session) -> None:
    user = make_user(db)
    session = UserSession(
        user_id=user.id,
        token_hash="t" * 64,
        csrf_token="c" * 64,
        expires_at=utcnow() + timedelta(hours=1),
    )
    db.add(session)
    db.commit()
    session_id = session.id

    db.delete(user)
    db.commit()

    assert db.get(UserSession, session_id) is None