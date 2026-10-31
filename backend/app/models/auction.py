from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .enums import AuctionStatus, str_enum
from .mixins import TimestampMixin

if TYPE_CHECKING:
    from .bid import Bid
    from .user import User


class Auction(Base, TimestampMixin):
    __tablename__ = "auctions"
    __table_args__ = (
        CheckConstraint("starting_price > 0", name="ck_auctions_price_positive"),
        CheckConstraint("min_decrement > 0", name="ck_auctions_decrement_positive"),
        CheckConstraint("ends_at > starts_at", name="ck_auctions_window"),
        Index("ix_auctions_status_ends_at", "status", "ends_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    buyer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Integer minor units (paise). Never a float.
    starting_price: Mapped[int] = mapped_column(Integer, nullable=False)
    min_decrement: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[AuctionStatus] = mapped_column(
        str_enum(AuctionStatus, name="auction_status"),
        default=AuctionStatus.DRAFT,
        nullable=False,
    )

    # Deliberately not a FK: auctions and bids reference each other, and SQLite
    # cannot add constraints after table creation. The service layer validates.
    winning_bid_id: Mapped[int | None] = mapped_column(Integer)

    buyer: Mapped["User"] = relationship()
    bids: Mapped[list["Bid"]] = relationship(
        back_populates="auction", order_by="Bid.created_at"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Auction id={self.id} title={self.title!r} status={self.status}>"

    @property
    def bid_count(self) -> int:
        return len(self.bids)

    @property
    def lowest_bid(self) -> int | None:
        return min((bid.amount for bid in self.bids), default=None)

    @property
    def buyer_email(self) -> str:
        """Denormalised owner identity for display; never used for authz."""
        return self.buyer.email