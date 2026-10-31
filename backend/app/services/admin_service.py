"""Administrator operations: user administration policy.

Deliberately narrow. An administrator can cancel auctions (via the auction
router), change roles, unlock accounts, and revoke sessions — but cannot
place, close, or award auctions. That separation of duties is enforced here
and in ``auction_service``.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Role, User, UserSession
from ..models.mixins import utcnow


class AdminError(Exception):
    """Base class for admin policy errors."""


class AdminForbidden(AdminError):
    pass


class AdminStateError(AdminError):
    pass


def active_session_counts(db: Session) -> dict[int, int]:
    statement = (
        select(UserSession.user_id, func.count())
        .where(UserSession.revoked_at.is_(None))
        .group_by(UserSession.user_id)
    )
    return {user_id: count for user_id, count in db.execute(statement).all()}


def list_users(
    db: Session, *, q: str | None = None, limit: int = 100, offset: int = 0
) -> list[tuple[User, int]]:
    statement = select(User).order_by(User.id.asc()).limit(limit).offset(offset)
    if q:
        statement = statement.where(User.email.contains(q.strip().lower()))
    users = list(db.scalars(statement))
    counts = active_session_counts(db)
    return [(user, counts.get(user.id, 0)) for user in users]


def _other_admins_exist(db: Session, *, exclude_id: int) -> bool:
    statement = (
        select(func.count())
        .select_from(User)
        .where(User.role == Role.ADMIN, User.id != exclude_id)
    )
    return bool(db.scalar(statement))


def change_role(db: Session, actor: User, target: User, role: Role) -> User:
    """Change a user's role, guarding against self-lockout and last-admin loss."""
    if target.id == actor.id:
        raise AdminForbidden("You cannot change your own role.")
    if target.role == role:
        return target
    if target.role == Role.ADMIN and not _other_admins_exist(db, exclude_id=target.id):
        raise AdminStateError("The last administrator cannot be demoted.")

    target.role = role
    db.commit()
    db.refresh(target)
    return target


def unlock(db: Session, target: User) -> User:
    target.locked_until = None
    target.failed_attempts = 0
    db.commit()
    db.refresh(target)
    return target


def revoke_all_sessions(db: Session, target: User) -> int:
    """Revoke every live session for a user (emergency lockout)."""
    now = utcnow()
    sessions = list(
        db.scalars(
            select(UserSession).where(
                UserSession.user_id == target.id,
                UserSession.revoked_at.is_(None),
            )
        )
    )
    for session in sessions:
        session.revoked_at = now
    db.commit()
    return len(sessions)
