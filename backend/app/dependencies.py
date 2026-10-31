"""Shared FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Role, User, UserSession
from .security.csrf import validate_csrf
from .security.sessions import get_session_by_token

settings = get_settings()


def _unauthorised() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Session"},
    )


def get_current_session(
    request: Request, db: Session = Depends(get_db)
) -> UserSession:
    token = request.cookies.get(settings.session_cookie_name)
    session = get_session_by_token(db, token)
    if session is None:
        raise _unauthorised()
    return session


def get_current_user(session: UserSession = Depends(get_current_session)) -> User:
    return session.user


def require_csrf(
    request: Request, session: UserSession = Depends(get_current_session)
) -> UserSession:
    """Require a valid session *and* a matching CSRF header.

    Returns the session so routes can revoke it (logout) without a second
    lookup.
    """
    validate_csrf(request, session)
    return session


def require_roles(*roles: Role) -> Callable[..., User]:
    """Build a dependency that allows only the given roles."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return user

    return dependency