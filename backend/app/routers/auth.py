"""Authentication routes: register, login, logout, and identity."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..dependencies import get_current_session, require_csrf
from ..models import Role, User
from ..schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserOut
from ..security.ratelimit import SlidingWindowLimiter
from ..security.sessions import (
    clear_session_cookie,
    create_session,
    get_session_by_token,
    revoke_session,
    set_session_cookie,
)
from ..services import auth_service

settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Per-IP and per-account windows. The IP window is wider because a campus NAT
# can legitimately share one address.
login_ip_limiter = SlidingWindowLimiter(
    limit=settings.login_rate_limit * 2,
    window_seconds=settings.login_rate_window_seconds,
)
login_account_limiter = SlidingWindowLimiter(
    limit=settings.login_rate_limit,
    window_seconds=settings.login_rate_window_seconds,
)
register_limiter = SlidingWindowLimiter(
    limit=settings.register_rate_limit,
    window_seconds=settings.register_rate_window_seconds,
)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def _auth_response(user: User, csrf_token: str) -> AuthResponse:
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=csrf_token)


def _start_session(
    db: Session, user: User, request: Request, response: Response
) -> AuthResponse:
    token, session = create_session(
        db,
        user,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, token)
    return _auth_response(user, session.csrf_token)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthResponse,
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    limit = register_limiter.check(f"ip:{_client_ip(request)}")
    if not limit.allowed:
        raise _too_many(limit.retry_after)

    try:
        user = auth_service.register_user(
            db,
            email=str(payload.email),
            password=payload.password,
            role=Role(payload.role),
        )
    except (auth_service.EmailAlreadyRegistered, IntegrityError):
        db.rollback()
        # Deliberately generic: do not confirm whether an address is in use.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration could not be completed with those details.",
        ) from None

    return _start_session(db, user, request, response)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    ip = _client_ip(request)

    ip_limit = login_ip_limiter.check(f"ip:{ip}")
    if not ip_limit.allowed:
        raise _too_many(ip_limit.retry_after)

    account_limit = login_account_limiter.check(f"email:{str(payload.email).lower()}")
    if not account_limit.allowed:
        raise _too_many(account_limit.retry_after)

    user = auth_service.authenticate(
        db, email=str(payload.email), password=payload.password
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Session"},
        )

    # Session rotation: revoke whatever this browser presented before issuing
    # a fresh token.
    existing_token = request.cookies.get(settings.session_cookie_name)
    if existing_token:
        existing = get_session_by_token(db, existing_token)
        if existing is not None:
            revoke_session(db, existing)

    return _start_session(db, user, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    revoke_session(db, session)
    clear_session_cookie(response)


@router.get("/me", response_model=AuthResponse)
def me(session=Depends(get_current_session)) -> AuthResponse:
    return _auth_response(session.user, session.csrf_token)