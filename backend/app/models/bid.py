from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .mixins import utcnow

if TYPE_CHECKING:
    from .auction import Auction
    from .user import User


class Bid(Base):
    """An immutable, signed bid.

    ``prev_hash`` links each bid to its predecessor and ``signature`` is an
    HMAC over the canonical payload (Milestone 6). Together they make the
    ledger tamper-evident.
    """

    __tablename__ = "bids"
    __table_args__ = (
        UniqueConstraint(
            "auction_id", "idempotency_key", name="uq_bids_auction_idempotency"
        ),
        CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
        Index("ix_bids_auction_amount", "auction_id", "amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(
        ForeignKey("auctions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    nonce: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    prev_hash: Mapped[str | None] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    auction: Mapped["Auction"] = relationship(back_populates="bids")
    seller: Mapped["User"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Bid id={self.id} auction={self.auction_id} amount={self.amount}>"