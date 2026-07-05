"""Password hashing and JWT issuance/verification.

Pure functions only -- no FastAPI dependencies here, those live in
app/api/dependencies.py. Kept separate so these can be unit tested without
spinning up the app.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

DEFAULT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed stored hash -- never let this crash the login endpoint.
        return False


class InvalidTokenError(Exception):
    pass


def create_access_token(
    *,
    claims: dict[str, Any],
    secret: str,
    algorithm: str = DEFAULT_ALGORITHM,
    expires_minutes: int = 60,
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=expires_minutes)
    payload = {**claims, "iat": now, "exp": now + expires_delta}
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str, *, secret: str, algorithm: str = DEFAULT_ALGORITHM) -> dict[str, Any]:
    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
