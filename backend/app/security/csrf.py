"""CSRF validation for authenticated state-changing requests.

This is a synchroniser-token pattern: the token is bound to the server-side
session and must be echoed in the ``X-CSRF-Token`` header. Unauthenticated
endpoints (login, register) are protected by the Origin check in ``main.py``.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from ..models import UserSession

CSRF_HEADER = "X-CSRF-Token"


def validate_csrf(request: Request, session: UserSession) -> None:
    supplied = request.headers.get(CSRF_HEADER, "")
    if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )