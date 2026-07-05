"""Persistence for the ``users`` table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user
