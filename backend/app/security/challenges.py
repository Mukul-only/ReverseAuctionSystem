"""Signed, short-lived challenges for the second login factor.

When a password check passes but the account has TOTP enabled, the login route
returns no session. Instead it issues an opaque, tamper-evident ticket that the
client must present alongside a valid TOTP code. The ticket is signed with the
application secret (``itsdangerous``) and expires quickly, so it cannot be
replayed after the fact or forged without the key.
"""

from __future__ import annotations

import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import get_settings

_SALT = "mfa-login-challenge"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt=_SALT)


def issue(user_id: int) -> str:
    """Mint a challenge binding one user to a fresh nonce."""
    return _serializer().dumps({"uid": user_id, "nonce": secrets.token_urlsafe(12)})


class ChallengeError(Exception):
    """Raised when a challenge is missing, malformed, or expired."""


def resolve(token: str) -> int:
    """Return the user id from a valid challenge, or raise ``ChallengeError``."""
    max_age = get_settings().mfa_challenge_seconds
    try:
        data = _serializer().loads(token, max_age=max_age)
    except SignatureExpired as error:
        raise ChallengeError("This verification step expired. Sign in again.") from error
    except BadSignature as error:
        raise ChallengeError("Invalid verification challenge.") from error

    if not isinstance(data, dict) or not isinstance(data.get("uid"), int):
        raise ChallengeError("Invalid verification challenge.")
    return int(data["uid"])
