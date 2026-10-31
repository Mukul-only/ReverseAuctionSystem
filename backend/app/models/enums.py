"""Domain enums shared by models, schemas, and services."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class Role(StrEnum):
    BUYER = "buyer"
    SELLER = "seller"
    ADMIN = "admin"


class AuctionStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    AWARDED = "awarded"
    CANCELLED = "cancelled"


def str_enum(enum_type: type[StrEnum], *, name: str, length: int = 16) -> SAEnum:
    """Store the enum's *values* (not member names) as a checked VARCHAR."""
    return SAEnum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda members: [member.value for member in members],
    )