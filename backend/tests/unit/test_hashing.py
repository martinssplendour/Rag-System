"""Unit tests for content hashing used for duplicate detection."""

from app.utils.hashing import sha256_hex


def test_sha256_hex_is_deterministic():
    assert sha256_hex(b"hello") == sha256_hex(b"hello")


def test_sha256_hex_differs_for_different_content():
    assert sha256_hex(b"hello") != sha256_hex(b"world")


def test_sha256_hex_matches_known_value():
    import hashlib

    assert sha256_hex(b"") == hashlib.sha256(b"").hexdigest()
