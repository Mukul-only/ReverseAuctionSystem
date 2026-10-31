"""TOTP second-factor helpers: secret generation, encryption, and verification.

Secrets are encrypted at rest with AES-256-GCM under a key derived from the
application secret with HKDF. The stored blob is ``base64(nonce || ciphertext)``
and AAD binds it to the user id, so a ciphertext copied onto another account
fails to decrypt.

Verification accepts a one-step clock skew and advances a stored step counter,
which blocks replay of a code that was already used.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import time

import pyotp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings
from .crypto import hkdf_sha256

_ENC_SALT = b"revauction/totp-secret/v1"
_NONCE_BYTES = 12
_PENDING_AAD = b"totp-pending"

DEFAULT_ISSUER = "Reverse Auctions"
VALID_WINDOW = 1


def _encryption_key() -> bytes:
    settings = get_settings()
    return hkdf_sha256(
        ikm=settings.secret_key.encode("utf-8"),
        salt=_ENC_SALT,
        info=b"totp-secret-encryption",
        length=32,
    )


def _aad(user_id: int | None) -> bytes:
    return _PENDING_AAD if user_id is None else f"user:{user_id}".encode("ascii")


def encrypt_secret(secret: str, *, user_id: int | None = None) -> str:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(_encryption_key()).encrypt(
        nonce, secret.encode("ascii"), _aad(user_id)
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(token: str, *, user_id: int | None = None) -> str:
    """Decrypt a stored secret. Raises ``ValueError`` on any tampering."""
    try:
        blob = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, base64.binascii.Error) as error:  # type: ignore[attr-defined]
        raise ValueError("Malformed TOTP secret.") from error

    if len(blob) <= _NONCE_BYTES:
        raise ValueError("Malformed TOTP secret.")

    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        plaintext = AESGCM(_encryption_key()).decrypt(nonce, ciphertext, _aad(user_id))
    except InvalidTag as error:
        raise ValueError("TOTP secret failed authentication.") from error
    return plaintext.decode("ascii")


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account: str, issuer: str = DEFAULT_ISSUER) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def generate_code(secret: str) -> str:
    """Current code for a secret — used by the seed and the attack demo."""
    return pyotp.TOTP(secret).now()


def _current_step() -> int:
    return int(time.time()) // 30


def match_step(secret: str, code: str) -> int | None:
    """Return the counter matched by ``code`` within the skew window, or None."""
    code = code.strip().replace(" ", "")
    if not code.isdigit() or not (6 <= len(code) <= 8):
        return None

    totp = pyotp.TOTP(secret)
    now = _current_step()
    for delta in (0, -1, 1):
        step = now + delta
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def verify_code(secret: str, code: str, *, last_step: int | None = None) -> int | None:
    """Verify a code and reject replays of an already-accepted step.

    Returns the matched counter so the caller can persist it, or ``None`` when
    the code is wrong, malformed, or already used.
    """
    step = match_step(secret, code)
    if step is None:
        return None
    if last_step is not None and step <= last_step:
        return None
    return step
