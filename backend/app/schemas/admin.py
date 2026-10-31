"""Schemas for the admin console: users, audit, and security events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    totp_enabled: bool
    failed_attempts: int
    locked_until: datetime | None
    active_sessions: int
    created_at: datetime


class RoleChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["buyer", "seller", "admin"]


class AuditEventOut(BaseModel):
    seq: int
    actor_id: int | None
    actor_email: EmailStr | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, object]
    prev_hash: str | None
    hash: str
    created_at: datetime


class AuditVerifyReport(BaseModel):
    event_count: int
    checked: int
    valid: bool
    first_invalid_seq: int | None = None
    reason: str | None = None
    head_seq: int | None = None
    head_hash: str | None = None


class AnchorOut(BaseModel):
    seq: int | None
    hash: str | None
    event_count: int
    signature: str


class SessionRevocationOut(BaseModel):
    revoked: int
