"""Unit tests for the bid-signing primitives."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.security.crypto import (
    HASH_BYTES,
    SIGNATURE_HEX_LENGTH,
    auction_signing_key,
    canonical_bid_payload,
    hkdf_sha256,
    sign_payload,
    signature_matches,
)

CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, 123456)


def payload(**overrides: object) -> bytes:
    values: dict[str, object] = {
        "auction_id": 7,
        "seller_id": 11,
        "amount": 995_000,
        "nonce": "a" * 32,
        "created_at": CREATED_AT,
        "prev_hash": None,
    }
    values.update(overrides)
    return canonical_bid_payload(**values)  # type: ignore[arg-type]


def test_hkdf_is_deterministic_and_sized() -> None:
    first = hkdf_sha256(ikm=b"secret", salt=b"salt", info=b"info")
    second = hkdf_sha256(ikm=b"secret", salt=b"salt", info=b"info")

    assert first == second
    assert len(first) == HASH_BYTES


def test_hkdf_separates_contexts() -> None:
    alpha = hkdf_sha256(ikm=b"secret", salt=b"salt", info=b"auction:1")
    beta = hkdf_sha256(ikm=b"secret", salt=b"salt", info=b"auction:2")

    assert alpha != beta


def test_hkdf_rejects_invalid_lengths() -> None:
    with pytest.raises(ValueError):
        hkdf_sha256(ikm=b"secret", salt=b"salt", info=b"info", length=0)
    with pytest.raises(ValueError):
        hkdf_sha256(
            ikm=b"secret", salt=b"salt", info=b"info", length=255 * HASH_BYTES + 1
        )


def test_auction_keys_are_isolated_per_auction() -> None:
    assert auction_signing_key(1) != auction_signing_key(2)
    assert len(auction_signing_key(1)) == HASH_BYTES


def test_signature_is_hex_and_verifies() -> None:
    key = auction_signing_key(7)
    signature = sign_payload(key, payload())

    assert len(signature) == SIGNATURE_HEX_LENGTH
    int(signature, 16)
    assert signature_matches(key, payload(), signature)


def test_signature_detects_an_altered_field() -> None:
    key = auction_signing_key(7)
    signature = sign_payload(key, payload())

    assert not signature_matches(key, payload(amount=994_999), signature)
    assert not signature_matches(key, payload(nonce="b" * 32), signature)
    assert not signature_matches(key, payload(seller_id=12), signature)


def test_signature_is_bound_to_the_auction_key() -> None:
    signature = sign_payload(auction_signing_key(7), payload())

    assert not signature_matches(auction_signing_key(8), payload(), signature)


def test_prev_hash_is_part_of_the_signed_payload() -> None:
    assert payload() != payload(prev_hash="b" * 64)


def test_timestamp_precision_is_stable() -> None:
    document = payload().decode("utf-8")

    assert "2026-01-01T12:00:00.123456" in document