"""Argon2id password hashing.

Parameters follow the OWASP minimum guidance for Argon2id (19 MiB, t=2, p=1)
with a comfortable margin: 64 MiB, t=3, p=4. Verification is constant-time
inside argon2-cffi.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,  # KiB == 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Return a salted Argon2id hash."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True only when ``password`` matches ``password_hash``.

    All verification failures collapse to ``False`` so callers cannot
    distinguish a malformed hash from a wrong password.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than the current ones."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True