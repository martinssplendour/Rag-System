"""Unit tests for password hashing and JWT issuance/verification."""

import time

import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret-not-for-real-use-and-long-enough-for-hs256"


def test_hash_password_produces_a_different_string_than_the_input():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_verify_password_accepts_the_correct_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_the_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_a_malformed_hash_without_raising():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_hash_password_uses_a_fresh_salt_each_time():
    first = hash_password("same password")
    second = hash_password("same password")
    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_create_and_decode_access_token_round_trips_claims():
    token, expires_in = create_access_token(
        claims={"sub": "user-1", "workspace_id": "ws-1"}, secret=SECRET, expires_minutes=60
    )
    assert expires_in == 3600
    claims = decode_access_token(token, secret=SECRET)
    assert claims["sub"] == "user-1"
    assert claims["workspace_id"] == "ws-1"


def test_decode_access_token_rejects_wrong_secret():
    token, _ = create_access_token(claims={"sub": "user-1", "workspace_id": "ws-1"}, secret=SECRET)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret="a-different-secret")


def test_decode_access_token_rejects_expired_token():
    token, _ = create_access_token(
        claims={"sub": "user-1", "workspace_id": "ws-1"}, secret=SECRET, expires_minutes=0
    )
    time.sleep(1.2)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret=SECRET)


def test_decode_access_token_rejects_garbage_input():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", secret=SECRET)
