"""Second-factor enrolment and verification policy.

Enrolment is a two-step handshake:

1. ``begin`` stores an encrypted, *unverified* secret (``totp_enabled`` stays
   false) and returns the provisioning URI.
2. ``confirm`` requires a live code from that secret before it is marked
   enabled, so a mis-scanned QR never locks the user out.

Enabling, disabling, and enrolling all need the account password again. That
way a stolen session alone cannot add an attacker's authenticator or strip the
factor off the account.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User
from ..security.passwords import verify_password
from ..security import totp as totp_utils

DEFAULT_ISSUER = totp_utils.DEFAULT_ISSUER


class MfaError(Exception):
    """Base class for second-factor policy errors."""


class MfaPasswordError(MfaError):
    """The supplied password did not match."""


class MfaStateError(MfaError):
    """The requested transition is not valid for the account's state."""


class MfaCodeError(MfaError):
    """The supplied code was wrong, malformed, or replayed."""


def _check_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise MfaPasswordError


def begin_enrolment(db: Session, user: User, *, password: str) -> tuple[str, str]:
    """Generate and store a pending secret; return ``(secret, otpauth_uri)``."""
    _check_password(user, password)
    if user.totp_enabled:
        raise MfaStateError("Two-factor authentication is already enabled.")

    secret = totp_utils.generate_secret()
    user.totp_secret_enc = totp_utils.encrypt_secret(secret, user_id=user.id)
    user.totp_enabled = False
    user.totp_last_step = None
    db.commit()

    uri = totp_utils.provisioning_uri(
        secret, account=user.email, issuer=DEFAULT_ISSUER
    )
    return secret, uri


def confirm_enrolment(db: Session, user: User, *, password: str, code: str) -> None:
    _check_password(user, password)
    if user.totp_enabled:
        raise MfaStateError("Two-factor authentication is already enabled.")
    if not user.totp_secret_enc:
        raise MfaStateError("Start enrolment before confirming a code.")

    secret = _decrypt(user)
    step = totp_utils.verify_code(secret, code)
    if step is None:
        raise MfaCodeError("That code is not valid. Check the clock and retry.")

    user.totp_enabled = True
    # The enrolment code is not consumed: the replay guard is applied on the
    # login and disable paths, so the same 30-second window stays usable for
    # the first sign-in.
    user.totp_last_step = None
    db.commit()


def disable(db: Session, user: User, *, password: str, code: str) -> None:
    """Remove the factor. Requires the password *and* a current code."""
    _check_password(user, password)
    if not user.totp_enabled:
        raise MfaStateError("Two-factor authentication is not enabled.")

    secret = _decrypt(user)
    step = totp_utils.verify_code(secret, code, last_step=user.totp_last_step)
    if step is None:
        raise MfaCodeError("That code is not valid. Check the clock and retry.")

    user.totp_secret_enc = None
    user.totp_enabled = False
    user.totp_last_step = None
    db.commit()


def verify_login_code(db: Session, user: User, *, code: str) -> bool:
    """Check a login code and advance the replay guard on success."""
    if not user.totp_enabled or not user.totp_secret_enc:
        raise MfaStateError("Two-factor authentication is not enabled.")

    secret = _decrypt(user)
    step = totp_utils.verify_code(secret, code, last_step=user.totp_last_step)
    if step is None:
        return False

    user.totp_last_step = step
    db.commit()
    return True


def _decrypt(user: User) -> str:
    try:
        return totp_utils.decrypt_secret(user.totp_secret_enc or "", user_id=user.id)
    except ValueError as error:
        # A stored secret that fails authentication means tampering or a key
        # rotation; refuse rather than silently trusting it.
        raise MfaStateError("Stored secret could not be read.") from error


def enabled_for(user: User) -> bool:
    return bool(user.totp_enabled and user.totp_secret_enc)
