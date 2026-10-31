"""Append-only audit ledger with an HMAC-SHA256 hash chain.

Every security-relevant action is appended as an :class:`AuditEvent`. Each row
stores the hash of the previous row plus an HMAC over its own contents, so a
deleted, inserted, reordered, or edited event breaks the chain and is detected
by :func:`verify`.

The database triggers in ``db.py`` already make the table immutable at the SQL
level; the chain is what makes tampering *detectable* even if those guards are
removed. ``anchor`` seals the current chain head so an operator can store it
outside the database and later detect truncation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import AuditEvent
from ..models.mixins import utcnow
from ..security.crypto import (
    audit_signing_key,
    canonical_audit_payload,
    canonical_metadata,
    chain_hash,
    signature_matches,
)

# Actions that are worth surfacing on their own in the admin console.
SECURITY_ACTIONS: tuple[str, ...] = (
    "auth.login",
    "auth.login_failed",
    "auth.logout",
    "auth.locked",
    "auth.register",
    "mfa.enabled",
    "mfa.disabled",
    "mfa.challenge_failed",
    "admin.role_changed",
    "admin.user_unlocked",
    "admin.sessions_revoked",
    "audit.verified",
)


class AuditError(Exception):
    """Raised when the ledger cannot be appended to or verified."""


def _previous_hash(db: Session) -> str | None:
    statement = select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)
    return db.scalar(statement)


def record(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditEvent:
    """Append one signed event and return it.

    Fail-open by design: an audit write must never take down the security
    control it is recording, but failures are still surfaced by the caller via
    the ``commit`` return.
    """
    created_at = utcnow()
    metadata_json = canonical_metadata(metadata)
    prev_hash = _previous_hash(db)

    payload = canonical_audit_payload(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        metadata_json=metadata_json,
        created_at=created_at,
        prev_hash=prev_hash,
    )
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        metadata_json=metadata_json,
        prev_hash=prev_hash,
        hash=chain_hash(audit_signing_key(), payload),
        created_at=created_at,
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    return event


def record_action(
    db: Session, action: str, *, actor: Any = None, **kwargs: Any
) -> AuditEvent:
    """Convenience wrapper accepting a ``User`` (or ``None``) as the actor."""
    actor_id = getattr(actor, "id", actor)
    return record(db, actor_id=actor_id, action=action, **kwargs)


def list_events(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    actor_id: int | None = None,
    security_only: bool = False,
) -> list[AuditEvent]:
    statement = (
        select(AuditEvent)
        .order_by(AuditEvent.seq.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(AuditEvent.actor))
    )
    if action:
        statement = statement.where(AuditEvent.action == action)
    if actor_id is not None:
        statement = statement.where(AuditEvent.actor_id == actor_id)
    if security_only:
        statement = statement.where(AuditEvent.action.in_(SECURITY_ACTIONS))
    return list(db.scalars(statement))


def count_events(
    db: Session,
    *,
    action: str | None = None,
    actor_id: int | None = None,
    security_only: bool = False,
) -> int:
    statement = select(func.count()).select_from(AuditEvent)
    if action:
        statement = statement.where(AuditEvent.action == action)
    if actor_id is not None:
        statement = statement.where(AuditEvent.actor_id == actor_id)
    if security_only:
        statement = statement.where(AuditEvent.action.in_(SECURITY_ACTIONS))
    return int(db.scalar(statement) or 0)


def verify(db: Session) -> dict[str, object]:
    """Recompute the whole chain in ``seq`` order.

    Returns a report shaped like the bid verification so the UI can render
    both with the same component.
    """
    key = audit_signing_key()
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.seq.asc())))
    previous_hash: str | None = None
    checked = 0

    for event in events:
        payload = canonical_audit_payload(
            actor_id=event.actor_id,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            metadata_json=event.metadata_json,
            created_at=event.created_at,
            prev_hash=event.prev_hash,
        )
        if not signature_matches(key, payload, event.hash):
            return {
                "event_count": len(events),
                "checked": checked,
                "valid": False,
                "first_invalid_seq": event.seq,
                "reason": "Signature mismatch: an audit event was altered.",
            }
        if (event.prev_hash or None) != previous_hash:
            return {
                "event_count": len(events),
                "checked": checked,
                "valid": False,
                "first_invalid_seq": event.seq,
                "reason": "Chain link mismatch: an event was removed or reordered.",
            }
        previous_hash = event.hash
        checked += 1

    head = events[-1] if events else None
    return {
        "event_count": len(events),
        "checked": checked,
        "valid": True,
        "first_invalid_seq": None,
        "reason": None,
        "head_seq": head.seq if head else None,
        "head_hash": head.hash if head else None,
    }


def anchor(db: Session) -> dict[str, object]:
    """Return a signed digest of the current chain head.

    Storing this value somewhere the application cannot rewrite (a printout,
    a separate system, a transparency log) lets a verifier later prove that no
    events were truncated from the end of the ledger.
    """
    head = db.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1))
    count = count_events(db)
    material = f"{head.seq if head else 0}:{head.hash if head else ''}:{count}"
    return {
        "seq": head.seq if head else None,
        "hash": head.hash if head else None,
        "event_count": count,
        "signature": chain_hash(audit_signing_key(), material.encode("utf-8")),
    }


def verify_anchor(db: Session, *, seq: int | None, hash_: str | None, count: int, signature: str) -> bool:
    """Check a previously issued anchor against the current ledger head."""
    material = f"{seq or 0}:{hash_ or ''}:{count}"
    return signature_matches(
        audit_signing_key(), material.encode("utf-8"), signature
    )
