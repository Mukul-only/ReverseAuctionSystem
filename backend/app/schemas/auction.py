from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from ..models import AuctionStatus
from ..security.text import sanitize_plain_text, sanitize_single_line


class AuctionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=5000)

    # Integer minor units (paise). The UI converts from rupees.
    starting_price: int = Field(gt=0, le=10**12)
    min_decrement: int = Field(gt=0, le=10**12)
    currency: Literal["INR"] = "INR"

    duration_hours: int = Field(default=48, gt=0, le=720)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        cleaned = sanitize_single_line(value)
        if len(cleaned) < 3:
            raise ValueError("Title must contain at least 3 visible characters.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return sanitize_plain_text(value)

    @model_validator(mode="after")
    def _decrement_fits(self) -> AuctionCreate:
        if self.min_decrement > self.starting_price:
            raise ValueError("Minimum decrement cannot exceed the starting price.")
        return self


class AuctionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    buyer_id: int
    buyer_email: EmailStr
    title: str
    description: str
    starting_price: int
    min_decrement: int
    currency: str
    starts_at: datetime
    ends_at: datetime
    status: AuctionStatus
    winning_bid_id: int | None
    created_at: datetime

    # Derived, read-only.
    bid_count: int
    lowest_bid: int | None