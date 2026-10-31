"""Registration, authentication, and lockout policy."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Role, User
from ..models.mixins import utcnow
from ..security.passwords import hash_password, needs_rehash, verify_password

settings = get_settings()

# Timing equaliser: an unknown email still pays for one Argon2 verification,
# so response time does not reveal whether the account exists.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(24))


class EmailAlreadyRegistered(Exception):
    """Raised when registration targets an existing address."""


def register_user(
    db: Session, *, email: str, password: str, role: Role
) -> User:
    normalised = email.strip().lower()
    existing = db.scalar(select(User.id).where(User.email == normalised))
    if existing is not None:
        raise EmailAlreadyRegistered

    user = User(
        email=normalised,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    """Return the user on success, otherwise ``None``.

    Failures increment a counter; hitting the threshold locks the account for
    a cooldown window. Every failure path costs one Argon2 verification.
    """
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    now = utcnow()

    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None

    if user.locked_until is not None and user.locked_until > now:
        verify_password(password, _DUMMY_HASH)
        return None

    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.lockout_threshold:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
        db.commit()
        return None

    user.failed_attempts = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    db.commit()
    return user