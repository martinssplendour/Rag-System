"""Registration/login use case.

Owns password hashing, duplicate-email detection, workspace creation, and
JWT issuance. Route handlers (app/api/routes/auth.py) call only this
module -- see modularity checklist layer boundaries.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password
from app.domain.errors import ServiceError
from app.repositories.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import TokenResponse


def _is_configured_admin(email: str, settings: Settings) -> bool:
    return email.strip().lower() in settings.admin_email_set


def _issue_token(user: User, settings: Settings) -> TokenResponse:
    if settings.auth_mode == "disabled" and not settings.jwt_secret:
        return TokenResponse(
            access_token="auth-disabled-local-session",
            expires_in=0,
            workspace_id=user.workspace_id,
            is_admin=user.is_admin,
        )
    access_token, expires_in = create_access_token(
        claims={
            "sub": user.id,
            "workspace_id": user.workspace_id,
            "email": user.email,
            "is_admin": user.is_admin,
        },
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expires_minutes,
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        workspace_id=user.workspace_id,
        is_admin=user.is_admin,
    )


async def register(*, session: AsyncSession, settings: Settings, email: str, password: str) -> TokenResponse:
    user_repo = UserRepository(session)
    existing = await user_repo.get_by_email(email)
    if existing is not None:
        raise ServiceError("EMAIL_ALREADY_REGISTERED", "An account with this email already exists.", 409)

    user = User(
        id=uuid4().hex,
        email=email,
        password_hash=hash_password(password),
        workspace_id=uuid4().hex,
        is_admin=_is_configured_admin(email, settings),
    )
    await user_repo.create(user)
    await session.commit()
    return _issue_token(user, settings)


async def login(*, session: AsyncSession, settings: Settings, email: str, password: str) -> TokenResponse:
    user_repo = UserRepository(session)
    user = await user_repo.get_by_email(email)
    # Deliberately identical error for "no such user" and "wrong password" --
    # distinguishing them lets an attacker enumerate registered emails.
    if user is None or not verify_password(password, user.password_hash):
        raise ServiceError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)
    if _is_configured_admin(user.email, settings) and not user.is_admin:
        user.is_admin = True
        await session.commit()
    return _issue_token(user, settings)
