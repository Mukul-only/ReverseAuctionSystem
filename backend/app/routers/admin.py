"""Administrator routes: user administration, audit viewer, security events.

Every route requires an admin whose second factor is enrolled
(:func:`app.dependencies.require_admin_mfa`). Mutations additionally require a
CSRF token, and every state change is itself written to the audit ledger.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import require_admin_mfa, require_csrf
from ..models import AuditEvent, Role, User, UserSession
from ..schemas.admin import (
    AdminUserOut,
    AnchorOut,
    AuditEventOut,
    AuditVerifyReport,
    RoleChangeRequest,
    SessionRevocationOut,
)
from ..services import admin_service, audit_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _audit_out(event: AuditEvent) -> AuditEventOut:
    try:
        metadata = json.loads(event.metadata_json)
    except (ValueError, TypeError):  # pragma: no cover - defensive
        metadata = {}
    return AuditEventOut(
        seq=event.seq,
        actor_id=event.actor_id,
        actor_email=event.actor.email if event.actor else None,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        metadata=metadata if isinstance(metadata, dict) else {"value": metadata},
        prev_hash=event.prev_hash,
        hash=event.hash,
        created_at=event.created_at,
    )


def _user_out(user: User, active_sessions: int) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        role=user.role.value,
        totp_enabled=user.totp_enabled,
        failed_attempts=user.failed_attempts,
        locked_until=user.locked_until,
        active_sessions=active_sessions,
        created_at=user.created_at,
    )


def _audit(db: Session, action: str, *, actor: User, entity_id: int | str | None = None, metadata: dict[str, object] | None = None) -> None:
    try:
        audit_service.record(
            db,
            actor_id=actor.id,
            action=action,
            entity_type="user",
            entity_id=entity_id,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - auditing must not break the action
        db.rollback()


# --- Users ---------------------------------------------------------------


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    q: str | None = Query(default=None, max_length=254),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin_mfa),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    return [
        _user_out(user, count)
        for user, count in admin_service.list_users(db, q=q, limit=limit, offset=offset)
    ]


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
def change_role(
    user_id: int,
    payload: RoleChangeRequest,
    admin: User = Depends(require_admin_mfa),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    previous = target.role.value

    try:
        target = admin_service.change_role(db, admin, target, Role(payload.role))
    except admin_service.AdminForbidden as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(error)
        ) from None
    except admin_service.AdminStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None

    if previous != payload.role:
        _audit(
            db,
            "admin.role_changed",
            actor=admin,
            entity_id=target.id,
            metadata={"from": previous, "to": payload.role, "target": target.email},
        )
    return _user_out(target, admin_service.active_session_counts(db).get(target.id, 0))


@router.post("/users/{user_id}/unlock", response_model=AdminUserOut)
def unlock_user(
    user_id: int,
    admin: User = Depends(require_admin_mfa),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    target = admin_service.unlock(db, target)
    _audit(db, "admin.user_unlocked", actor=admin, entity_id=target.id)
    return _user_out(target, admin_service.active_session_counts(db).get(target.id, 0))


@router.post("/users/{user_id}/revoke-sessions", response_model=SessionRevocationOut)
def revoke_sessions(
    user_id: int,
    admin: User = Depends(require_admin_mfa),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> SessionRevocationOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    revoked = admin_service.revoke_all_sessions(db, target)
    _audit(
        db,
        "admin.sessions_revoked",
        actor=admin,
        entity_id=target.id,
        metadata={"revoked": revoked},
    )
    return SessionRevocationOut(revoked=revoked)


# --- Audit ledger --------------------------------------------------------


@router.get("/audit", response_model=list[AuditEventOut])
def list_audit(
    action: str | None = Query(default=None, max_length=64),
    actor_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin_mfa),
    db: Session = Depends(get_db),
) -> list[AuditEventOut]:
    events = audit_service.list_events(
        db, limit=limit, offset=offset, action=action, actor_id=actor_id
    )
    return [_audit_out(event) for event in events]


@router.get("/security-events", response_model=list[AuditEventOut])
def list_security_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin_mfa),
    db: Session = Depends(get_db),
) -> list[AuditEventOut]:
    events = audit_service.list_events(
        db, limit=limit, offset=offset, security_only=True
    )
    return [_audit_out(event) for event in events]


@router.post("/audit/verify", response_model=AuditVerifyReport)
def verify_audit(
    admin: User = Depends(require_admin_mfa),
    _csrf: UserSession = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AuditVerifyReport:
    report = audit_service.verify(db)
    _audit(
        db,
        "audit.verified",
        actor=admin,
        metadata={"valid": report["valid"], "event_count": report["event_count"]},
    )
    return AuditVerifyReport(**report)


@router.get("/audit/anchor", response_model=AnchorOut)
def audit_anchor(
    admin: User = Depends(require_admin_mfa),
    db: Session = Depends(get_db),
) -> AnchorOut:
    """Return a signed head digest the operator can store off-system."""
    return AnchorOut(**audit_service.anchor(db))
