"""Bid signing primitives.

Every bid is sealed with HMAC-SHA256 under a key derived per auction with
HKDF. The canonical payload is a deterministic JSON document built only from
stored columns, so the signature can be recomputed during verification.

Honest limitation: this protects against database-level tampering, not against
a fully malicious server that controls the signing key. The threat model is
documented in ``docs/``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

from ..config import get_settings

HASH_BYTES = 32
SIGNATURE_HEX_LENGTH = HASH_BYTES * 2

# A domain-separated salt keeps these keys distinct from any other use of the
# application secret.
_HKDF_SALT = b"revauction/bid-signing/v1"
_INFO_PREFIX = b"auction:"


def hkdf_sha256(
    *,
    ikm: bytes,
    salt: bytes,
    info: bytes,
    length: int = HASH_BYTES,
) -> bytes:
    """RFC 5869 HKDF with SHA-256 (extract-then-expand)."""
    if length < 1 or length > 255 * HASH_BYTES:
        raise ValueError("HKDF length must be between 1 and 8160 bytes")

    prk = hmac.new(salt, ikm, hashlib.sha256).digest()

    okm = bytearray()
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(
            prk, block + info + bytes([counter]), hashlib.sha256
        ).digest()
        okm.extend(block)
        counter += 1

    return bytes(okm[:length])


def auction_signing_key(auction_id: int) -> bytes:
    """Derive a 256-bit signing key unique to one auction."""
    settings = get_settings()
    return hkdf_sha256(
        ikm=settings.secret_key.encode("utf-8"),
        salt=_HKDF_SALT,
        info=_INFO_PREFIX + str(auction_id).encode("ascii"),
    )


def _canonical_timestamp(created_at: datetime) -> str:
    """Naive UTC with fixed microsecond precision.

    SQLite round-trips this exact format, so the signature survives a reload.
    """
    return created_at.strftime("%Y-%m-%dT%H:%M:%S.%f")


def canonical_bid_payload(
    *,
    auction_id: int,
    seller_id: int,
    amount: int,
    nonce: str,
    created_at: datetime,
    prev_hash: str | None,
) -> bytes:
    """Build the byte string that gets signed.

    Sorted keys and fixed separators make the JSON independent of dict order.
    """
    document = {
        "auction_id": auction_id,
        "seller_id": seller_id,
        "amount": amount,
        "nonce": nonce,
        "created_at": _canonical_timestamp(created_at),
        "prev_hash": prev_hash or "",
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sign_payload(key: bytes, payload: bytes) -> str:
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def signature_matches(key: bytes, payload: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_payload(key, payload), signature)