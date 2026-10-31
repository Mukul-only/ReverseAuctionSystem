"""Authentication routes: register, login, MFA, logout, and identity."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..dependencies import get_current_session, require_csrf, require_roles
from ..models import Role, User
from ..schemas.auth import (
    AuthResponse,
    LoginRequest,
    LoginResponse,
    MfaCodeRequest,
    MfaLoginRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    RegisterRequest,
    UserOut,
)
from ..security import challenges
from ..security.ratelimit import SlidingWindowLimiter
from ..security.sessions import (
    clear_session_cookie,
    create_session,
    get_session_by_token,
    revoke_session,
    set_session_cookie,
)
from ..services import audit_service, auth_service, mfa_service

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
mfa_limiter = SlidingWindowLimiter(
    limit=settings.mfa_rate_limit,
    window_seconds=settings.mfa_rate_window_seconds,
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


def _safe_audit(db: Session, **kwargs) -> None:
    """Audit writes must never break the action they describe."""
    try:
        audit_service.record(db, **kwargs)
    except Exception:  # noqa: BLE001 - auditing is best-effort at the edge
        db.rollback()


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

    _safe_audit(
        db, actor_id=user.id, action="auth.register", entity_type="user", entity_id=user.id
    )
    return _start_session(db, user, request, response)


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    ip = _client_ip(request)
    email = str(payload.email).lower()

    ip_limit = login_ip_limiter.check(f"ip:{ip}")
    if not ip_limit.allowed:
        raise _too_many(ip_limit.retry_after)

    account_limit = login_account_limiter.check(f"email:{email}")
    if not account_limit.allowed:
        raise _too_many(account_limit.retry_after)

    user = auth_service.authenticate(
        db, email=str(payload.email), password=payload.password
    )
    if user is None:
        _safe_audit(
            db,
            actor_id=None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=email,
            metadata={"ip": ip},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Session"},
        )

    # A second factor is required: hand back a short-lived signed challenge
    # instead of a session. No cookie is set until the code is verified.
    if mfa_service.enabled_for(user):
        challenge = challenges.issue(user.id)
        _safe_audit(
            db,
            actor_id=user.id,
            action="mfa.challenge_issued",
            entity_type="user",
            entity_id=user.id,
            metadata={"ip": ip},
        )
        return LoginResponse(
            mfa_required=True,
            challenge=challenge,
            user=None,
            csrf_token=None,
        )

    return _establish(db, user, request, response)


@router.post("/mfa/login", response_model=LoginResponse)
def mfa_login(
    payload: MfaLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Complete a login that paused for a second factor."""
    ip = _client_ip(request)
    limit = mfa_limiter.check(f"ip:{ip}")
    if not limit.allowed:
        raise _too_many(limit.retry_after)

    try:
        user_id = challenges.resolve(payload.challenge)
    except challenges.ChallengeError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid challenge."
        )

    if not mfa_service.verify_login_code(db, user, code=payload.code):
        _safe_audit(
            db,
            actor_id=user.id,
            action="mfa.challenge_failed",
            entity_type="user",
            entity_id=user.id,
            metadata={"ip": ip},
        )
        limit = mfa_limiter.check(f"user:{user.id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication code.",
        )

    return _establish(db, user, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    _safe_audit(
        db,
        actor_id=session.user_id,
        action="auth.logout",
        entity_type="user",
        entity_id=session.user_id,
    )
    revoke_session(db, session)
    clear_session_cookie(response)


@router.get("/me", response_model=AuthResponse)
def me(session=Depends(get_current_session)) -> AuthResponse:
    return _auth_response(session.user, session.csrf_token)


# --- Second factor management (all require a live session + CSRF) --------


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(
    payload: MfaSetupRequest,
    user: User = Depends(require_roles(Role.BUYER, Role.SELLER, Role.ADMIN)),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MfaSetupResponse:
    limit = mfa_limiter.check(f"user:{user.id}")
    if not limit.allowed:
        raise _too_many(limit.retry_after)

    try:
        secret, uri = mfa_service.begin_enrolment(db, user, password=payload.password)
    except mfa_service.MfaPasswordError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Password is incorrect."
        ) from None
    except mfa_service.MfaStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None
    return MfaSetupResponse(secret=secret, otpauth_uri=uri, issuer=mfa_service.DEFAULT_ISSUER)


@router.post("/mfa/verify", response_model=AuthResponse)
def mfa_verify(
    payload: MfaCodeRequest,
    user: User = Depends(require_roles(Role.BUYER, Role.SELLER, Role.ADMIN)),
    session=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AuthResponse:
    limit = mfa_limiter.check(f"user:{user.id}")
    if not limit.allowed:
        raise _too_many(limit.retry_after)

    try:
        mfa_service.confirm_enrolment(
            db, user, password=payload.password, code=payload.code
        )
    except mfa_service.MfaPasswordError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Password is incorrect."
        ) from None
    except (mfa_service.MfaStateError, mfa_service.MfaCodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None

    _safe_audit(
        db,
        actor_id=user.id,
        action="mfa.enabled",
        entity_type="user",
        entity_id=user.id,
    )
    return _auth_response(user, session.csrf_token)


@router.post("/mfa/disable", response_model=AuthResponse)
def mfa_disable(
    payload: MfaCodeRequest,
    user: User = Depends(require_roles(Role.BUYER, Role.SELLER, Role.ADMIN)),
    session=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AuthResponse:
    limit = mfa_limiter.check(f"user:{user.id}")
    if not limit.allowed:
        raise _too_many(limit.retry_after)

    try:
        mfa_service.disable(db, user, password=payload.password, code=payload.code)
    except mfa_service.MfaPasswordError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Password is incorrect."
        ) from None
    except (mfa_service.MfaStateError, mfa_service.MfaCodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None

    _safe_audit(
        db,
        actor_id=user.id,
        action="mfa.disabled",
        entity_type="user",
        entity_id=user.id,
    )
    return _auth_response(user, session.csrf_token)


def _establish(
    db: Session, user: User, request: Request, response: Response
) -> LoginResponse:
    """Rotate any prior session, start a fresh one, and record the login."""
    existing_token = request.cookies.get(settings.session_cookie_name)
    if existing_token:
        existing = get_session_by_token(db, existing_token)
        if existing is not None:
            revoke_session(db, existing)

    auth = _start_session(db, user, request, response)
    _safe_audit(
        db,
        actor_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        metadata={"ip": _client_ip(request), "role": user.role.value},
    )
    return LoginResponse(mfa_required=False, user=auth.user, csrf_token=auth.csrf_token)
