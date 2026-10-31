from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BidCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Integer minor units (paise).
    amount: int = Field(gt=0, le=10**12)
    # Client-generated so a retry after a timeout cannot double-bid.
    idempotency_key: str = Field(
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class BidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    auction_id: int
    seller_id: int
    seller_email: EmailStr
    amount: int
    nonce: str
    prev_hash: str | None
    signature: str
    created_at: datetime


class ChainVerification(BaseModel):
    auction_id: int
    bid_count: int
    checked: int
    valid: bool
    first_invalid_bid_id: int | None = None
    reason: str | None = None