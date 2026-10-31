"""Opaque, server-side sessions.

The browser receives a random bearer token in an HttpOnly cookie. Only its
SHA-256 hash is stored in the database, so a database leak does not yield
usable session tokens.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User, UserSession
from ..models.mixins import utcnow

settings = get_settings()

SESSION_TOKEN_BYTES = 32
_LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    db: Session,
    user: User,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, UserSession]:
    """Create a session and return the raw token plus the stored row.

    The raw token is never persisted.
    """
    now = utcnow()
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)

    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token, session


def get_session_by_token(db: Session, token: str | None) -> UserSession | None:
    """Resolve a bearer token to an active session, enforcing idle expiry."""
    if not token:
        return None

    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    if session is None or session.revoked_at is not None:
        return None

    now = utcnow()
    if session.expires_at <= now:
        return None

    idle_deadline = session.last_seen_at + timedelta(
        minutes=settings.session_idle_minutes
    )
    if idle_deadline <= now:
        revoke_session(db, session)
        return None

    # Throttle writes: one last_seen update per minute is plenty.
    if now - session.last_seen_at >= _LAST_SEEN_WRITE_INTERVAL:
        session.last_seen_at = now
        db.commit()

    return session


def revoke_session(db: Session, session: UserSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )